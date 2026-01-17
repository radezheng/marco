import os

from openai import OpenAI

# Usage:
#   export AZURE_OPENAI_ENDPOINT='https://<resource>.openai.azure.com/openai/v1/'
#   export AZURE_OPENAI_API_KEY='...'
#   export AZURE_OPENAI_DEPLOYMENT='gpt-5.2-chat'
endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
deployment_name = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5.2-chat").strip()
api_key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()

if not endpoint or not api_key:
    raise SystemExit("Missing AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_API_KEY")

client = OpenAI(
    base_url=endpoint,
    api_key=api_key
)

completion = client.chat.completions.create(
    model=deployment_name,
    messages=[
        {
            "role": "user",
            "content": "What is the capital of France?",
        }
    ],
    temperature=1,
)

print(completion.choices[0].message)