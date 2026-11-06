import os
import uvicorn

# Root entrypoint for hosting platforms (Botkeep / Pterodactyl / Docker)
# Allows running with: python main.py

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    # Pterodactyl / Botkeep provides SERVER_PORT; other cloud hosts provide PORT
    port = int(os.environ.get("SERVER_PORT", os.environ.get("PORT", "8000")))
    
    print(f"Starting Logistics Document Processing & OCR Service on {host}:{port}")
    uvicorn.run("backend.app.main:app", host=host, port=port)

