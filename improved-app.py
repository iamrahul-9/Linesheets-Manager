from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import os
import sqlite3
import pandas as pd
import json
from werkzeug.utils import secure_filename
from datetime import datetime
import logging

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.secret_key = '12345678'  # Add a secret key for session management

# Set up logging
logging.basicConfig(level=logging.DEBUG)

# Ensure the upload folder exists
try:
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    logging.info(f"Upload folder '{app.config['UPLOAD_FOLDER']}' created or already exists.")
except Exception as e:
    logging.error(f"Error creating upload folder '{app.config['UPLOAD_FOLDER']}': {e}")

def init_db():
    with sqlite3.connect("products.db") as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS products (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        style TEXT,
                        data TEXT,
                        image TEXT)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS line_sheets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT,
                        filename TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        season TEXT,
                        configuration TEXT)''')
init_db()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == 'admin' and password == 'minkas':  # Replace with your credentials
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    return render_template('index.html')

@app.route('/analyze-excel', methods=['POST'])
def analyze_excel():
    if 'excel' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['excel']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    try:
        # Determine if it's Excel or CSV
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)
        
        # Get all available columns
        columns = df.columns.tolist()
        
        # Check for size columns (typically named S, M, L, XL, XXL, etc.)
        size_columns = [col for col in columns if col.strip().upper() in ['S', 'M', 'L', 'XL', 'XXL', '1X', '2X', '3X']]
        
        # Remove size columns from the main columns list
        remaining_columns = [col for col in columns if col not in size_columns]
        
        return jsonify({
            "columns": remaining_columns,
            "size_columns": size_columns
        })
    except Exception as e:
        logging.error(f"Error analyzing Excel file: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/upload-excel', methods=['POST'])
def upload_excel():
    try:
        file = request.files['excel']
        
        if file.filename == '':
            return "No selected file.", 400
            
        # Gather form data
        title = request.form['title'].upper()
        season = request.form.get('season', 'SPRING/SUMMER 2025')  # Default to SPRING/SUMMER
        selected_fields = request.form.getlist('fields[]')
        show_size_ratios = request.form.get('show_size_ratios') == 'true'
        show_images = request.form.get('show_images') == 'true'
        
        # Save configuration for future reference
        config = {
            "title": title,
            "season": season,
            "selected_fields": selected_fields,
            "show_size_ratios": show_size_ratios,
            "show_images": show_images
        }
        
        # Determine if it's Excel or CSV
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)
        
        # Identify size columns
        size_columns = [col for col in df.columns if col.strip().upper() in ['S', 'M', 'L', 'XL', 'XXL', '1X', '2X', '3X']]
        
        # Create a subdirectory for the line sheet images using the title
        line_sheet_dir = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(title))
        try:
            os.makedirs(line_sheet_dir, exist_ok=True)
            logging.info(f"Line sheet directory '{line_sheet_dir}' created or already exists.")
        except Exception as e:
            logging.error(f"Error creating line sheet directory '{line_sheet_dir}': {e}")
            return f"Error creating directory for line sheet images: {e}", 500
        
        with sqlite3.connect("products.db") as conn:
            conn.execute("DELETE FROM products")  # Clear existing data
            
            # Skip the first row (header) and process each row in the dataframe
            for _, row in df.iloc[1:].iterrows():
                style = str(row.get('STYLE#', ''))
                if not style or pd.isna(style):
                    continue  # Skip rows without a style number
                
                # Create a data dictionary for this product
                product_data = {}
                for field in selected_fields:
                    if field in row and not pd.isna(row[field]):
                        product_data[field] = str(row[field])
                
                # Handle sizes
                if show_size_ratios and size_columns:
                    sizes_data = {}
                    for size_col in size_columns:
                        if size_col in row and not pd.isna(row[size_col]):
                            sizes_data[size_col] = int(row[size_col]) if str(row[size_col]).isdigit() else 0
                    product_data['sizes_ratio'] = sizes_data
                
                # Generate size range string (e.g., "S-XXL")
                available_sizes = [size for size in size_columns if size in row and not pd.isna(row[size]) and row[size] > 0]
                if available_sizes:
                    min_size = min(available_sizes, key=lambda x: ['S', 'M', 'L', 'XL', 'XXL', '1X', '2X', '3X'].index(x) if x in ['S', 'M', 'L', 'XL', 'XXL', '1X', '2X', '3X'] else 999)
                    max_size = max(available_sizes, key=lambda x: ['S', 'M', 'L', 'XL', 'XXL', '1X', '2X', '3X'].index(x) if x in ['S', 'M', 'L', 'XL', 'XXL', '1X', '2X', '3X'] else -1)
                    product_data['size_range'] = f"{min_size}-{max_size}"
                
                # Look for image
                image_path = ''
                if show_images:
                    image_filename = f"{style}.jpg"  # Assuming images are in JPG format
                    if os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], image_filename)):
                        try:
                            # Move the image to the line sheet subdirectory
                            new_image_path = os.path.join(line_sheet_dir, image_filename)
                            os.rename(os.path.join(app.config['UPLOAD_FOLDER'], image_filename), new_image_path)
                            image_path = os.path.relpath(new_image_path, 'static')
                        except Exception as e:
                            logging.error(f"Error moving image {image_filename}: {e}")
                
                # Insert product into database
                conn.execute("INSERT INTO products (style, data, image) VALUES (?, ?, ?)",
                            (style, json.dumps(product_data), image_path))
        
        # Generate and save the line sheet HTML
        with sqlite3.connect("products.db") as conn:
            products = conn.execute("SELECT * FROM products").fetchall()
        
        # Filter out incomplete entries
        products = [(id, style, json.loads(data), image) for id, style, data, image in products if data]
        
        # Determine template based on show_images flag
        template_name = 'line_sheets.html' if show_images else 'line_sheets_table.html'
        
        rendered_html = render_template(
            template_name, 
            products=products, 
            title=title,
            season=season,
            fields=selected_fields,
            show_size_ratios=show_size_ratios,
            pdf_view=True
        )
        
        # Save the rendered HTML to a file with a unique filename
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = f'line_sheets_{timestamp}.html'
        filepath = os.path.join('static', filename)
        with open(filepath, 'w') as file:
            file.write(rendered_html)
        
        # Save the line sheet metadata to the database
        with sqlite3.connect("products.db") as conn:
            conn.execute(
                "INSERT INTO line_sheets (title, filename, season, configuration) VALUES (?, ?, ?, ?)", 
                (title, filename, season, json.dumps(config))
            )
        
        return redirect(url_for('view_line_sheet', filename=filename))
    
    except Exception as e:
        logging.error(f"Error in upload_excel: {e}")
        return f"An error occurred: {e}", 500

@app.route('/line_sheets')
def line_sheets():
    title = request.args.get('title', 'MINKAS LINE SHEETS')
    with sqlite3.connect("products.db") as conn:
        products = conn.execute("SELECT * FROM products").fetchall()
    
    # Parse JSON data for each product
    products = [(id, style, json.loads(data), image) for id, style, data, image in products if data]
    
    return render_template('line_sheets.html', products=products, title=title)

@app.route('/list_line_sheets')
def list_line_sheets():
    with sqlite3.connect("products.db") as conn:
        line_sheets = conn.execute("SELECT * FROM line_sheets ORDER BY created_at DESC").fetchall()
    
    # Convert created_at to datetime objects
    line_sheets = [(id, title, filename, datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S'), season, configuration) for id, title, filename, created_at, season, configuration in line_sheets]
    
    return render_template('list_line_sheets.html', line_sheets=line_sheets)

@app.route('/view_line_sheet/<filename>')
def view_line_sheet(filename):
    return redirect(url_for('static', filename=filename))

@app.route('/regenerate_line_sheet/<int:id>')
def regenerate_line_sheet(id):
    with sqlite3.connect("products.db") as conn:
        line_sheet = conn.execute("SELECT * FROM line_sheets WHERE id = ?", (id,)).fetchone()
        
    if not line_sheet:
        logging.error(f"Line sheet with id {id} not found.")
        return "Line sheet not found", 404
    
    # Extract configuration
    config_str = line_sheet[5]
    if not config_str:
        logging.error(f"Configuration for line sheet with id {id} is empty.")
        return "Configuration is empty", 400
    
    try:
        config = json.loads(config_str)
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON configuration for line sheet with id {id}: {e}")
        return "Invalid configuration format", 400
    
    # Re-render the line sheet with the saved configuration
    with sqlite3.connect("products.db") as conn:
        products = conn.execute("SELECT * FROM products").fetchall()
    
    # Parse JSON data for each product
    try:
        products = [(id, style, json.loads(data), image) for id, style, data, image in products if data]
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding product data for line sheet with id {id}: {e}")
        return "Invalid product data format", 500
    
    # Determine template based on show_images flag
    template_name = 'line_sheets.html' if config.get('show_images', True) else 'line_sheets_table.html'
    
    rendered_html = render_template(
        template_name, 
        products=products, 
        title=config.get('title', 'MINKAS LINE SHEETS'),
        season=config.get('season', 'SPRING/SUMMER 2025'),
        fields=config.get('selected_fields', []),
        show_size_ratios=config.get('show_size_ratios', False),
        pdf_view=True
    )
    
    # Save the rendered HTML to a file with a unique filename
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    filename = f'line_sheets_{timestamp}.html'
    filepath = os.path.join('static', filename)
    with open(filepath, 'w') as file:
        file.write(rendered_html)
    
    # Save the updated line sheet metadata to the database
    with sqlite3.connect("products.db") as conn:
        conn.execute(
            "INSERT INTO line_sheets (title, filename, season, configuration) VALUES (?, ?, ?, ?)", 
            (config.get('title', 'MINKAS LINE SHEETS'), filename, config.get('season', 'SPRING/SUMMER 2025'), json.dumps(config))
        )
    
    return redirect(url_for('view_line_sheet', filename=filename))

if __name__ == '__main__':
    app.run(debug=True)
