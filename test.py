#!/usr/bin/env python3
import requests
import sys

API_BASE = "http://localhost:8100"
API_KEY = "demo-free-key"

def test_pdf_extract():
    # Create a dummy PDF file (minimal valid PDF)
    pdf_content = b'%PDF-1.4\n1 0 obj\n<</Type/Catalog/Pages 2 0 R>>\nendobj\n2 0 obj\n<</Type/Pages/Kids[3 0 R]/Count 1>>\nendobj\n3 0 obj\n<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>\nendobj\nxref\n0 4\n0000000000 65535 f\n0000000010 00000 n\n0000000053 00000 n\n0000000102 00000 n\ntrailer\n<</Size 4/Root 1 0 R>>\nstartxref\n149\n%%EOF'
    files = {'file': ('test.pdf', pdf_content, 'application/pdf')}
    headers = {'X-API-Key': API_KEY}
    resp = requests.post(f"{API_BASE}/pdf/extract", files=files, headers=headers)
    print(f"PDF Extract Status: {resp.status_code}")
    print(resp.json())

def test_price_monitor():
    headers = {'X-API-Key': API_KEY, 'Content-Type': 'application/json'}
    data = {
        "product_url": "https://example.com/product",
        "email": "test@example.com",
        "interval_hours": 24
    }
    resp = requests.post(f"{API_BASE}/monitor/price", json=data, headers=headers)
    print(f"Price Monitor Status: {resp.status_code}")
    print(resp.json())

if __name__ == "__main__":
    test_pdf_extract()
    test_price_monitor()