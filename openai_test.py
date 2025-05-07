from openai import OpenAI

client = OpenAI(
  base_url="https://openrouter.ai/api/v1",
  api_key="*******************",
)

completion = client.chat.completions.create(
  extra_headers={
    "HTTP-Referer": "", # Optional. Site URL for rankings on openrouter.ai.
    "X-Title": "", # Optional. Site title for rankings on openrouter.ai.
  },
  extra_body={},
  model="qwen/qwen3-32b:free",
  messages=[
    {
      "role": "user",
      "content": "test"
    }
  ]
)
print(completion.choices[0].message.content)
