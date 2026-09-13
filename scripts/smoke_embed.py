# smoke_embed.py — throwaway. Prove we can reach the API and get a vector back.

# Reads the .env file and loads its contents into environment variables,
# so that GEMINI_API_KEY becomes visible to the process.
# Run from the repo root:  python -m scripts.smoke_embed
from dotenv import load_dotenv

# Google's official SDK. genai holds the client, types holds config objects.
from google import genai
from google.genai import types

load_dotenv()

# Client() looks for GEMINI_API_KEY in the environment by itself —
# which is why load_dotenv() must run before this line.
client = genai.Client()

result = client.models.embed_content(
    model="gemini-embedding-2",
    contents="def login(user, password):",
    config=types.EmbedContentConfig(output_dimensionality=768),
)

# result.embeddings is a list with one entry per input. We sent one input.
vector = result.embeddings[0].values

print(f"length: {len(vector)}")
print(f"first 5: {vector[:5]}")


# (venv) (base) amrit@Amrittts-Macbook-Air repolens % python smoke_embed.py
# length: 768
# first 5: [0.021262538, 0.01562464, 0.011859454, 0.02702611, -0.0012511706]
# (venv) (base) amrit@Amrittts-Macbook-Air repolens % 