from dotenv import load_dotenv
import os, pathlib

# Automatically load .env from project root
project_root = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=project_root / ".env")