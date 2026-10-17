# pipeline/llm.py — ask pipeline, step 3: the prompt becomes an answer.
#
# The only module that calls a chat model.
#
# Sibling of embedder.py - both wrap an external API client, so both are
# classes: one instance is built per process and passed down, never rebuilt per
# call. Building one per call would mean a new client and a new TLS handshake
# every question.
#
# Handed a finished prompt, returns the model's reply. It knows nothing about
# repositories, chunks, or how the prompt was built - that is prompter.py's job.


from google import genai
from google.genai import types          # GenerateContentConfig lives here
from src.pipeline.retry import RetryPolicy

import json                             # the reply is a JSON string - parse it here

from dotenv import load_dotenv          # reads .env into os.environ
load_dotenv()                           # So genai.Client() can find GEMINI_API_KEY.

import logging 
logger = logging.getLogger(__name__)


class Llm:
    
    def __init__(self, client=None, model="gemini-3.5-flash-lite", temperature=0, retry=None):
        if client is None:
            client = genai.Client()   # handle to api, holds https sockets to google
        
        if retry is None:
            retry = RetryPolicy()
        
        self.client = client
        self.retry = retry
        self.model = model
        self.temperature = temperature
        
    def generate(self, prompt, system_instruction=None, schema=None):
        """Send one finished prompt to the model and return its reply.

        IN
          prompt  one string - the complete instruction, already assembled
                  by the caller. This method never edits it.
          schema  dict or None - a JSON schema the reply must match. The
                  caller owns it (prompter.ANSWER_SCHEMA), so this class
                  stays usable for any shape.

        OUT
          with schema:     dict - the reply parsed, matching that schema
          without schema:  str  - the reply text, unchanged
        """
        # retry.run takes a callable and re-runs it on 429 / 5xx. The lambda
        # defers the call to retry.run, which decides when the request happens.
        #
        # response_schema switches on constrained decoding: the API limits which
        # tokens the model may emit, so the reply matches the shape. None = plain text.
        #
        # The mimetype is not optional - the SDK says "if response_schema is set, a
        # compatible response_mime_type must also be set". Alone it is only a hint,
        # and the model picks its own shape.
        
        response = self.retry.run(lambda: self.client.models.generate_content(
            model = self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=self.temperature,
                system_instruction=system_instruction,
                response_mime_type="application/json" if schema else None,
                response_schema=schema,
            ),
        ))
        
        # usage_metadata is what each call cost. Logged rather than returned,
        # because callers want the answer, not the accounting.
        usage = response.usage_metadata
        logger.info(
            "generated: %d prompt tokens, %d response tokens",
            usage.prompt_token_count,
            usage.candidates_token_count,
        )
        
        # With a schema, response.text is '{"answer": "...", "citations": [1, 6]}' -
        # a string. loads() makes it a dict so the caller can subscript it.
        # Without one the reply is prose, so it goes back untouched.
        if schema:
            return json.loads(response.text)
        
        return response.text
        

if __name__ == "__main__":
    llm = Llm()
    print(llm.generate("make me a mermaid diagram of tranformer architecture"))

        
        
    