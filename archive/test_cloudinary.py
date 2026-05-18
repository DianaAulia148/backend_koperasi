import cloudinary
import cloudinary.uploader
import os
from dotenv import load_dotenv

load_dotenv()

cloudinary.config( 
    cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME'), 
    api_key = os.getenv('CLOUDINARY_API_KEY'), 
    api_secret = os.getenv('CLOUDINARY_API_SECRET'),
    secure = True
)

print(f"Cloud Name: {os.getenv('CLOUDINARY_CLOUD_NAME')}")
print(f"API Key: {os.getenv('CLOUDINARY_API_KEY')}")
print(f"API Secret: {os.getenv('CLOUDINARY_API_SECRET')}")

try:
    print("Testing Cloudinary upload with a simple string...")
    result = cloudinary.uploader.upload("https://cloudinary-devres.cloudinary.com/image/upload/sample.jpg", folder="test")
    print("Upload Success!")
    print(f"Result URL: {result.get('secure_url')}")
except Exception as e:
    print(f"Upload Failed: {str(e)}")
