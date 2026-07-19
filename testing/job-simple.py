import os
import sys
from dotenv import load_dotenv
from google import genai  # Official Google Gen AI SDK

# Fix encoding issue for printing Rupee symbols and other Unicode on Windows
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Load environment variables from the project root .env
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))


def fetch_python_jobs(user_data):
    # 1. Verify that the API key is set in the environment
    if not os.environ.get("GEMINI_API_KEY"):
        print(
            "Error: GEMINI_API_KEY environment variable is not set.",
            file=sys.stderr,
        )
        print(
            "Please run: export GEMINI_API_KEY='your_key'", file=sys.stderr
        )
        sys.exit(1)

    print("Initializing Gemini Client...")
    client = genai.Client()

    # 2. Extract variables from user_data for better prompt readability
    role, city, ctc, experience = user_data

    # 3. Construct the prompt using an f-string to inject the parameters
    prompt = (
        f"Act as a professional technical recruiter. Based on the following criteria:\n"
        f"- Target Role: {role}\n"
        f"- Target City: {city}\n"
        f"- Target CTC Range: {ctc}\n"
        f"- Required Experience Level: {experience}\n\n"
        f"Provide a clean, structured Markdown table list of active matching job openings "
        f"in {city}'s prominent IT/corporate parks. For each position, include the company name, "
        f"specific tech hub location, exact role title, target CTC, and primary technical skillsets requested."
    )

    print("Querying Gemini API (using gemini-3.5-flash)...")

    try:
        # 4. Call the generate_content method
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
        )

        # 5. Print out the returned result
        print(f"\n=== Current Matching {role} Jobs in {city} ===")
        print(response.text)
        print("=====================================================")

    except Exception as e:
        print(f"An error occurred while hitting the API: {e}", file=sys.stderr)


if __name__ == "__main__":
    # Define parameters cleanly
    role = "Python Developer"
    city = "Mumbai"
    ctc = "4-8 LPA"
    experience = "2-3 years"

    user_data = [role, city, ctc, experience]

    # Pass the list into the function
    fetch_python_jobs(user_data)