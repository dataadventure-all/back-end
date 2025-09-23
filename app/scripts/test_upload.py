"""
Test script for upload endpoints
Save as: app/scripts/test_upload.py
"""

import requests
import json
import pandas as pd
import io
from pathlib import Path

# Base URL - adjust as needed
BASE_URL = "http://localhost:8000/api/v1"

def test_csv_upload():
    """Test CSV file upload"""
    print("\n=== Testing CSV Upload ===")
    
    # Create sample CSV data
    df = pd.DataFrame({
        'date': pd.date_range('2024-01-01', periods=10),
        'product': ['Product A', 'Product B'] * 5,
        'quantity': [10, 20, 15, 25, 30, 35, 40, 45, 50, 55],
        'price': [100.5, 200.0, 150.75, 250.25, 300.0, 350.5, 400.0, 450.75, 500.0, 550.25]
    })
    
    # Convert to CSV
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    csv_content = csv_buffer.getvalue()
    
    # Prepare files and data for upload
    files = {
        'file': ('test_data.csv', csv_content, 'text/csv')
    }
    data = {
        'name': 'Test Sales Data',
        'description': 'Sample sales data for testing'
    }
    
    # Send request
    response = requests.post(f"{BASE_URL}/upload/csv", files=files, data=data)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ CSV uploaded successfully!")
        print(f"   Dataset ID: {result['dataset_id']}")
        print(f"   Dataset Name: {result['dataset_name']}")
        print(f"   Rows: {result['file_info']['rows']}")
        print(f"   Columns: {result['file_info']['columns']}")
        return result['dataset_id']
    else:
        print(f"❌ CSV upload failed: {response.status_code}")
        print(f"   Error: {response.text}")
        return None

def test_excel_upload():
    """Test Excel file upload"""
    print("\n=== Testing Excel Upload ===")
    
    # Create sample Excel data
    df1 = pd.DataFrame({
        'date': pd.date_range('2024-01-01', periods=10),
        'sales': [1000, 1200, 1500, 1800, 2000, 2200, 2500, 2800, 3000, 3200],
        'region': ['North', 'South', 'East', 'West'] * 2 + ['North', 'South']
    })
    
    df2 = pd.DataFrame({
        'product_id': range(1, 6),
        'product_name': ['Product A', 'Product B', 'Product C', 'Product D', 'Product E'],
        'category': ['Electronics', 'Clothing', 'Electronics', 'Food', 'Clothing']
    })
    
    # Create Excel file in memory
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        df1.to_excel(writer, sheet_name='Sales', index=False)
        df2.to_excel(writer, sheet_name='Products', index=False)
    
    excel_content = excel_buffer.getvalue()
    
    # Prepare files and data for upload
    files = {
        'file': ('test_data.xlsx', excel_content, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    }
    data = {
        'sheet_name': 'Sales',
        'name': 'Test Excel Data',
        'description': 'Sample Excel data with multiple sheets'
    }
    
    # Send request
    response = requests.post(f"{BASE_URL}/upload/excel", files=files, data=data)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Excel uploaded successfully!")
        print(f"   Dataset ID: {result['dataset_id']}")
        print(f"   Dataset Name: {result['dataset_name']}")
        print(f"   Sheet: {result['file_info']['sheet_name']}")
        print(f"   Available Sheets: {result['file_info']['available_sheets']}")
        print(f"   Rows: {result['file_info']['rows']}")
        print(f"   Columns: {result['file_info']['columns']}")
        return result['dataset_id']
    else:
        print(f"❌ Excel upload failed: {response.status_code}")
        print(f"   Error: {response.text}")
        return None

def test_database_connection():
    """Test database connection upload"""
    print("\n=== Testing Database Connection ===")
    
    # Test with SQLite (easiest to test without actual database)
    credentials = {
        "db_type": "sqlite",
        "database": ":memory:",  # In-memory SQLite for testing
        "name": "Test SQLite DB",
        "description": "In-memory SQLite database for testing"
    }
    
    headers = {'Content-Type': 'application/json'}
    response = requests.post(
        f"{BASE_URL}/upload/database", 
        json=credentials,
        headers=headers
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Database connection successful!")
        print(f"   Connection ID: {result['connection_id']}")
        print(f"   Connection Name: {result['connection_name']}")
        print(f"   Database Type: {result['connection_info']['db_type']}")
        return result['connection_id']
    else:
        print(f"❌ Database connection failed: {response.status_code}")
        print(f"   Error: {response.text}")
        
    # Test with PostgreSQL (if available)
    print("\n   Testing PostgreSQL connection...")
    credentials_pg = {
        "db_type": "postgresql",
        "host": "localhost",
        "port": 5432,
        "username": "user",
        "password": "password",
        "database": "testdb",
        "name": "Test PostgreSQL",
        "description": "PostgreSQL test database"
    }
    
    response = requests.post(
        f"{BASE_URL}/upload/database", 
        json=credentials_pg,
        headers=headers
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"   ✅ PostgreSQL connection successful!")
        print(f"      Tables: {result['connection_info'].get('tables_count', 0)}")
    else:
        print(f"   ⚠️  PostgreSQL connection failed (this is expected if PostgreSQL is not running)")
        
    return None

def test_list_datasets():
    """Test listing uploaded datasets"""
    print("\n=== Testing List Datasets ===")
    
    response = requests.get(f"{BASE_URL}/datasets")
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Datasets retrieved successfully!")
        print(f"   Total datasets: {result['count']}")
        for dataset in result['datasets']:
            print(f"   - {dataset['name']} ({dataset['type']}): {dataset['rows']} rows, {dataset['columns']} columns")
    else:
        print(f"❌ Failed to list datasets: {response.status_code}")

def test_delete_dataset(dataset_id: str):
    """Test deleting a dataset"""
    if not dataset_id:
        print("\n=== Skipping Delete Test (no dataset ID) ===")
        return
        
    print(f"\n=== Testing Delete Dataset ({dataset_id}) ===")
    
    response = requests.delete(f"{BASE_URL}/datasets/{dataset_id}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Dataset deleted successfully!")
        print(f"   Message: {result['message']}")
    else:
        print(f"❌ Failed to delete dataset: {response.status_code}")

def main():
    """Run all tests"""
    print("=" * 50)
    print("Testing Upload Endpoints")
    print("=" * 50)
    
    # Test CSV upload
    csv_dataset_id = test_csv_upload()
    
    # Test Excel upload
    excel_dataset_id = test_excel_upload()
    
    # Test database connection
    connection_id = test_database_connection()
    
    # List all datasets
    test_list_datasets()
    
    # Test delete (optional)
    if csv_dataset_id:
        test_delete_dataset(csv_dataset_id)
        
    print("\n" + "=" * 50)
    print("Testing Complete!")
    print("=" * 50)

if __name__ == "__main__":
    main()