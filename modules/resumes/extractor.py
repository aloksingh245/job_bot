'''
Author:     Sai Vignesh Golla / Antigravity
License:    MIT License
            https://opensource.org/license/mit

Module to extract text and details from user resume PDF for AI context.
'''

import os
from typing import Optional

def extract_resume_text(pdf_path: Optional[str] = None) -> str:
    '''
    Extracts text content from a PDF resume.
    If pdf_path is missing or not found, checks common fallback locations.
    '''
    if not pdf_path or not os.path.exists(pdf_path):
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        candidates = [
            os.path.join(root_dir, "ALOK_KUMAR_SINGH.pdf"),
            "/Users/alokkumarsingh/Desktop/alok_resume/job apply bot/linkedin job apply/ALOK_KUMAR_SINGH.pdf",
            "/Users/alokkumarsingh/Desktop/alok_resume/RESUMEE/ALOK_KUMAR_SINGH.pdf",
            "ALOK_KUMAR_SINGH.pdf",
        ]
        for cand in candidates:
            if os.path.exists(cand):
                pdf_path = cand
                break

    if not pdf_path or not os.path.exists(pdf_path):
        return ""

    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        extracted = []
        for page in reader.pages:
            text = page.extract_text()
            if text and text.strip():
                extracted.append(text.strip())
        return "\n\n".join(extracted)
    except Exception as e:
        print(f"Failed to extract text from resume {pdf_path}: {e}")
        return ""
