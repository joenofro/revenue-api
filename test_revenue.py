#!/usr/bin/env python3
"""
Test script for revenue streams API endpoints
"""
import requests
import json

API_BASE = "http://localhost:8100"
API_KEY = "demo-free-key"

def test_revenue_streams():
    """Test the revenue streams endpoints"""
    headers = {'X-API-Key': API_KEY, 'Content-Type': 'application/json'}
    
    print("=== Testing Revenue Streams API ===")
    
    # 1. Create a revenue stream
    print("\n1. Creating revenue stream...")
    stream_data = {
        "name": "AIDAN Brain API",
        "category": "api",
        "monthly_revenue": 500.0,
        "potential_monthly": 5000.0,
        "growth_rate": 10.5,
        "notes": "AI memory and knowledge search API"
    }
    
    resp = requests.post(f"{API_BASE}/revenue/streams", json=stream_data, headers=headers)
    print(f"Create Status: {resp.status_code}")
    if resp.status_code == 200:
        result = resp.json()
        print(f"Created stream ID: {result.get('stream_id')}")
        stream_id = result.get('stream_id')
    else:
        print(f"Error: {resp.text}")
        return
    
    # 2. Get all revenue streams
    print("\n2. Getting all revenue streams...")
    resp = requests.get(f"{API_BASE}/revenue/streams", headers=headers)
    print(f"Get All Status: {resp.status_code}")
    if resp.status_code == 200:
        streams = resp.json()
        print(f"Found {len(streams)} revenue streams")
        for stream in streams:
            print(f"  - {stream['name']}: £{stream['monthly_revenue']}/month")
    
    # 3. Get specific revenue stream
    print(f"\n3. Getting stream ID {stream_id}...")
    resp = requests.get(f"{API_BASE}/revenue/streams/{stream_id}", headers=headers)
    print(f"Get Single Status: {resp.status_code}")
    if resp.status_code == 200:
        stream = resp.json()
        print(f"Stream details: {json.dumps(stream, indent=2)}")
    
    # 4. Update revenue stream
    print(f"\n4. Updating stream ID {stream_id}...")
    update_data = {
        "monthly_revenue": 750.0,
        "growth_rate": 12.0,
        "notes": "Updated: Added new pricing tiers"
    }
    resp = requests.put(f"{API_BASE}/revenue/streams/{stream_id}", json=update_data, headers=headers)
    print(f"Update Status: {resp.status_code}")
    if resp.status_code == 200:
        print("Update successful")
    
    # 5. Get revenue summary
    print("\n5. Getting revenue summary...")
    resp = requests.get(f"{API_BASE}/revenue/summary", headers=headers)
    print(f"Summary Status: {resp.status_code}")
    if resp.status_code == 200:
        summary = resp.json()
        print(f"Revenue Summary:")
        print(f"  Total streams: {summary['total_streams']}")
        print(f"  Monthly revenue: £{summary['total_monthly_revenue']:.2f}")
        print(f"  Potential revenue: £{summary['total_potential_revenue']:.2f}")
        print(f"  Revenue gap: £{summary['revenue_gap']:.2f}")
        print(f"  Avg growth rate: {summary['avg_growth_rate']:.1f}%")
    
    print("\n=== Revenue Streams API Test Complete ===")

if __name__ == "__main__":
    test_revenue_streams()