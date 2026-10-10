import os
from google import genai
from PIL import Image

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

image = Image.open("workspace_view.png").convert("RGB")

prompt = """
You are an industrial robotics scene analyst.

Analyze this workstation image and answer clearly.

Workstation rules:
- The red square is the COMPONENT SUPPLY zone.
- The green square is the ASSEMBLY KIT A destination zone.
- The red cube is the component that must be moved.
- The required task is to move the red cube from COMPONENT SUPPLY
  to the center of ASSEMBLY KIT A.
- Never choose COMPONENT SUPPLY as the place destination.

Tasks:
1. Identify the industrial zones visible in the image.
2. Identify the robot.
3. Identify the red component/object.
4. Describe where the red object is located relative to the colored zones.
5. State the required robot action using the workstation zone names.

Return the answer in this format:

ZONES:
- ...

ROBOT:
- ...

OBJECT:
- ...

RELATION:
- ...

ACTION PLAN:
- Pick: <object and source zone>
- Place: <destination zone>
"""

uploaded_file = client.files.upload(file="workspace_view.png")

response = client.interactions.create(
    model="gemini-robotics-er-2-preview",
    input=[
        {
            "type": "image",
            "uri": uploaded_file.uri,
            "mime_type": uploaded_file.mime_type,
        },
        {
            "type": "text",
            "text": prompt,
        },
    ],
)

print("\n===== GEMINI RESPONSE =====\n")
print(response.output_text)
