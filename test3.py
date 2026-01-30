import boto3
import pandas as pd
import openpyxl
from openpyxl.formatting.rule import ColorScaleRule
import io
import os
import urllib.parse

s3 = boto3.client('s3')

def generate_excel_report(bucket, key):
    # 1. Download CSV from S3 into memory
    response = s3.get_object(Bucket=bucket, Key=key)
    csv_content = response['Body'].read()
    
    # Read into Pandas
    read_file = pd.read_csv(io.BytesIO(csv_content))
    
    # --- YOUR ORIGINAL LOGIC STARTS HERE ---
    # I have adapted your original generate_report.py logic to work in memory
    
    # Create the Excel file in memory
    output = io.BytesIO()
    
    # Convert CSV to Excel initially
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        read_file.to_excel(writer, index=None, header=True)
    
    # Load workbook for formatting
    output.seek(0)
    book = openpyxl.load_workbook(output)
    sheet = book.active # Default sheet
    
    # Your original analysis logic
    # Note: You need to ensure 'conf_list' and 'ratio' functions are copied here 
    # or imported if you put them in a utils file.
    
    # (For brevity, I'm pasting the critical formatting logic)
    first_column = ['ConfigRule', 'Total', 'Compliant', '%', 'Prod-Com', 'Prod-Non', 'P%', 'Stg-Com', 'Stg-Non', 'S%', 'Dev-Com', 'Dev-Non', 'D%']
    
    # Create Report Sheet
    if 'Report' not in book.sheetnames:
        book.create_sheet('Report')
    ws = book['Report']
    ws.append(first_column)
    
    # ... [Insert your specific loop logic for stats here] ...
    # This matches lines 60-80 in your original script
    
    # Add Conditional Formatting (The Colors)
    # Green/Yellow/Red rules
    color_red = 'C0504D'
    color_yellow = 'F79646'
    color_green = '9BBB59'
    
    # Example rule from your code
    ws.conditional_formatting.add('D2:D200',
        ColorScaleRule(start_type='percentile', start_value=10, start_color=color_red,
                       mid_type='percentile', mid_value=50, mid_color=color_yellow,
                       end_type='percentile', end_value=90, end_color=color_green)
    )

    # --- END OF ORIGINAL LOGIC ---

    # 4. Save the result back to S3
    output.seek(0)
    new_key = key.replace('.csv', '.xlsx')
    s3.put_object(Bucket=bucket, Key=new_key, Body=output.getvalue())
    print(f"Report generated: s3://{bucket}/{new_key}")

def lambda_handler(event, context):
    # Get the object from the event (S3 Trigger)
    bucket = event['Records'][0]['s3']['bucket']['name']
    key = urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'], encoding='utf-8')

    try:
        print(f"Processing file: {key}")
        generate_excel_report(bucket, key)
        return "Success"
    except Exception as e:
        print(e)
        raise e