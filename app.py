from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from zoneinfo import ZoneInfo
import io
import pandas as pd
from sqlalchemy import or_


app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///warehouse.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)  # e.g., Switch, Router
    vendor = db.Column(db.String(50), nullable=False) # e.g., Cisco, Aruba
    model = db.Column(db.String(100), nullable=False, unique=True)
    items = db.relationship('Item', backref='category_rel', lazy=True)

class PropertyClient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False) # Client name or Ownership property
    items = db.relationship('Item', backref='owner_property', lazy=True)

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    serial_number = db.Column(db.String(100), unique=True, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    property_id = db.Column(db.Integer, db.ForeignKey('property_client.id'), nullable=True)
    status = db.Column(db.String(20), default='IN_STOCK')  # 'IN_STOCK' or 'EXITED'

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action = db.Column(db.String(20), nullable=False)
    timestamp = db.Column(db.DateTime, default=rome_now)  # Uses Europe/Rome local time
    comment = db.Column(db.String(255), nullable=True)

    item = db.relationship('Item', backref=db.backref('transactions', lazy=True))
    user = db.relationship('User', backref=db.backref('transactions', lazy=True))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes
@app.route('/')
@login_required
def index():
    categories = Category.query.all()
    inventory_summary = []
    
    total_in_stock = 0
    total_exited = 0

    for cat in categories:
        # Count items per category based on status
        in_stock_count = Item.query.filter_by(category_id=cat.id, status='IN_STOCK').count()
        exited_count = Item.query.filter_by(category_id=cat.id, status='EXITED').count()
        
        total_in_stock += in_stock_count
        total_exited += exited_count

        inventory_summary.append({
            'vendor': cat.vendor,
            'category': cat.name,
            'model': cat.model,
            'in_stock': in_stock_count,
            'exited': exited_count
        })

    metrics = {
        'total_registered': Item.query.count(),
        'total_in_stock': total_in_stock,
        'total_exited': total_exited,
        'total_categories': len(categories)
    }

    return render_template('index.html', summary=inventory_summary, metrics=metrics)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/manage', methods=['GET', 'POST'])
@login_required
def manage_metadata():
    if request.method == 'POST':
        form_type = request.form.get('form_type')
        if form_type == 'add_category':
            name = request.form.get('name')
            vendor = request.form.get('vendor')
            model = request.form.get('model')
            if not Category.query.filter_by(model=model).first():
                db.session.add(Category(name=name, vendor=vendor, model=model))
                db.session.commit()
                flash('New Model/Category added successfully!')
            else:
                flash('Model already exists!')
        elif form_type == 'add_property':
            prop_name = request.form.get('property_name')
            if not PropertyClient.query.filter_by(name=prop_name).first():
                db.session.add(PropertyClient(name=prop_name))
                db.session.commit()
                flash('New Property/Client added successfully!')
            else:
                flash('Property/Client already exists!')
        return redirect(url_for('manage_metadata'))
        
    categories = Category.query.all()
    properties = PropertyClient.query.all()
    return render_template('manage_metadata.html', categories=categories, properties=properties)

@app.route('/transaction', methods=['GET', 'POST'])
@login_required
def transaction():
    categories = Category.query.all()
    properties = PropertyClient.query.all()
    
    if request.method == 'POST':
        serial_number = request.form.get('serial_number', '').strip()
        action = request.form.get('action')
        category_id = request.form.get('category_id')
        property_id = request.form.get('property_id')
        comment = request.form.get('comment', '').strip()

        # Convert IDs safely
        cat_id = int(category_id) if category_id and category_id.isdigit() else None
        prop_id = int(property_id) if property_id and property_id.isdigit() else None

        item = Item.query.filter_by(serial_number=serial_number).first()

        if action == 'ENTRANCE':
            if item and item.status == 'IN_STOCK':
                flash(f'Error: Device {serial_number} is ALREADY in stock!')
                return redirect(url_for('transaction'))
            
            if not item:
                if not cat_id:
                    flash('Error: Category/Model selection required for new devices!')
                    return redirect(url_for('transaction'))
                item = Item(
                    serial_number=serial_number, 
                    category_id=cat_id, 
                    property_id=prop_id, 
                    status='IN_STOCK'
                )
                db.session.add(item)
            else:
                item.status = 'IN_STOCK'
                item.property_id = prop_id
                if cat_id:
                    item.category_id = cat_id
            
        elif action == 'EXIT':
            if not item or item.status == 'EXITED':
                flash(f'Error: Device {serial_number} is NOT currently in warehouse stock!')
                return redirect(url_for('transaction'))
            
            item.status = 'EXITED'

        # Log transaction history
        new_trans = Transaction(
            item=item, 
            user_id=current_user.id, 
            action=action, 
            comment=comment
        )
        db.session.add(new_trans)
        db.session.commit()
        
        flash(f'Successfully recorded {action} for Serial Number: {serial_number}')
        return redirect(url_for('index'))

    return render_template('log_transaction.html', categories=categories, properties=properties)

@app.route('/quick_exit/<int:item_id>', methods=['POST'])
@login_required
def quick_exit(item_id):
    item = Item.query.get_or_404(item_id)
    comment = request.form.get('comment', 'Manual exit from Report page').strip()

    if item.status == 'EXITED':
        flash(f'Device {item.serial_number} is already marked as EXITED!')
        return redirect(url_for('report'))

    item.status = 'EXITED'
    
    # Record movement in audit log
    new_trans = Transaction(
        item_id=item.id,
        user_id=current_user.id,
        action='EXIT',
        comment=comment
    )
    db.session.add(new_trans)
    db.session.commit()

    flash(f'Device {item.serial_number} marked as EXITED successfully!')
    return redirect(url_for('report'))

@app.route('/bulk_import', methods=['GET', 'POST'])
@login_required
def bulk_import():
    categories = Category.query.all()
    properties = PropertyClient.query.all()

    if request.method == 'POST':
        action = request.form.get('action')
        category_id = request.form.get('category_id')
        property_id = request.form.get('property_id')
        comment = request.form.get('comment', '').strip()
        uploaded_file = request.files.get('file')

        if not uploaded_file or uploaded_file.filename == '':
            flash('Error: No file selected for upload!')
            return redirect(url_for('bulk_import'))

        filename = uploaded_file.filename.lower()
        extracted_serials = []

        try:
            # 1. Parse Plain Text Files (.txt)
            if filename.endswith('.txt'):
                content = uploaded_file.read().decode('utf-8', errors='ignore')
                extracted_serials = [line.strip() for line in content.splitlines() if line.strip()]

            # 2. Parse CSV Files (.csv)
            elif filename.endswith('.csv'):
                df = pd.read_csv(uploaded_file, header=None)
                # Flatten all columns and extract non-empty strings
                extracted_serials = df.astype(str).values.flatten().tolist()
                extracted_serials = [s.strip() for s in extracted_serials if s.strip() and s.strip().lower() != 'nan']

            # 3. Parse Excel Files (.xlsx, .xls)
            elif filename.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(uploaded_file, header=None)
                extracted_serials = df.astype(str).values.flatten().tolist()
                extracted_serials = [s.strip() for s in extracted_serials if s.strip() and s.strip().lower() != 'nan']

            else:
                flash('Error: Unsupported file format! Please upload a .txt, .csv, or .xlsx file.')
                return redirect(url_for('bulk_import'))

        except Exception as e:
            flash(f'Error reading file: {str(e)}')
            return redirect(url_for('bulk_import'))

        # Clean serials (remove headers like "Serial Number" or "SN")
        clean_serials = []
        for sn in extracted_serials:
            cleaned = sn.replace('SN:', '').replace('S/N:', '').strip()
            if len(cleaned) >= 4 and cleaned.lower() not in ['serial', 'serial number', 'sn', 's/n', 'n/a']:
                clean_serials.append(cleaned)

        # Deduplicate while preserving order
        unique_serials = list(dict.fromkeys(clean_serials))

        if not unique_serials:
            flash('No valid serial numbers found in the uploaded file.')
            return redirect(url_for('bulk_import'))

        cat_id = int(category_id) if category_id and category_id.isdigit() else None
        prop_id = int(property_id) if property_id and property_id.isdigit() else None

        added_count = 0
        skipped_count = 0

        for sn in unique_serials:
            item = Item.query.filter_by(serial_number=sn).first()

            if action == 'ENTRANCE':
                if item and item.status == 'IN_STOCK':
                    skipped_count += 1
                    continue

                # Auto-detect category if not manually selected
                item_cat_id = cat_id
                if not item_cat_id:
                    upper_sn = sn.upper()
                    if upper_sn.startswith(('FOC', 'JAE')):
                        cisco_cat = Category.query.filter(Category.vendor.ilike('%cisco%')).first()
                        item_cat_id = cisco_cat.id if cisco_cat else None
                    elif upper_sn.startswith(('FP', 'FG', 'PU3')):
                        forti_cat = Category.query.filter(Category.vendor.ilike('%fortinet%')).first()
                        item_cat_id = forti_cat.id if forti_cat else None

                if not item:
                    if not item_cat_id:
                        skipped_count += 1
                        continue
                    item = Item(serial_number=sn, category_id=item_cat_id, property_id=prop_id, status='IN_STOCK')
                    db.session.add(item)
                else:
                    item.status = 'IN_STOCK'
                    item.property_id = prop_id
                    if item_cat_id:
                        item.category_id = item_cat_id

            elif action == 'EXIT':
                if not item or item.status == 'EXITED':
                    skipped_count += 1
                    continue
                item.status = 'EXITED'

            # Audit log
            db.session.add(Transaction(item=item, user_id=current_user.id, action=action, comment=comment or 'Bulk File Import'))
            added_count += 1

        db.session.commit()
        flash(f'Bulk processing complete! Successfully processed: {added_count} items. Skipped/Duplicates: {skipped_count}.')
        return redirect(url_for('report'))

    return render_template('bulk_import.html', categories=categories, properties=properties)

@app.route('/bulk_action', methods=['POST'])
@login_required
def bulk_action():
    item_ids = request.form.getlist('selected_items')
    action = request.form.get('action')
    comment = request.form.get('comment', '').strip()

    if not item_ids:
        flash('Warning: No items were selected!')
        return redirect(url_for('report'))

    updated_count = 0
    for item_id in item_ids:
        if not item_id.isdigit():
            continue
            
        item = Item.query.get(int(item_id))
        if not item:
            continue

        if action == 'EXIT':
            if item.status != 'EXITED':
                item.status = 'EXITED'
                db.session.add(Transaction(item_id=item.id, user_id=current_user.id, action='EXIT', comment=comment or 'Bulk exit from Report page'))
                updated_count += 1

        elif action == 'UPDATE_COMMENT':
            if comment:
                latest_tx = Transaction.query.filter_by(item_id=item.id).order_by(Transaction.timestamp.desc()).first()
                if latest_tx:
                    latest_tx.comment = comment
                else:
                    db.session.add(Transaction(item_id=item.id, user_id=current_user.id, action=item.status, comment=comment))
                updated_count += 1

        elif action == 'DELETE':
            Transaction.query.filter_by(item_id=item.id).delete()
            db.session.delete(item)
            updated_count += 1

    db.session.commit()
    flash(f'Successfully processed bulk {action} on {updated_count} selected item(s)!')
    return redirect(url_for('report'))
@app.route('/report')
@login_required
def report():
    selected_model = request.args.get('model_filter', '')
    selected_property = request.args.get('property_filter', '')
    search_query = request.args.get('search_query', '').strip()

    # Base query joined across related tables for comprehensive searching
    query = Item.query.outerjoin(Category).outerjoin(PropertyClient).outerjoin(Transaction)

    if selected_model:
        query = query.filter(Category.model == selected_model)
    if selected_property and selected_property.isdigit():
        query = query.filter(Item.property_id == int(selected_property))

    # Global multi-field search logic
    if search_query:
        search_pattern = f'%{search_query}%'
        query = query.filter(
            or_(
                Item.serial_number.ilike(search_pattern),
                Item.status.ilike(search_pattern),
                Category.name.ilike(search_pattern),
                Category.vendor.ilike(search_pattern),
                Category.model.ilike(search_pattern),
                PropertyClient.name.ilike(search_pattern),
                Transaction.comment.ilike(search_pattern)
            )
        )

    # Deduplicate items in case multiple transaction rows match the search query
    filtered_items = query.distinct().all()

    # Enrich item objects with entrance/exit timestamps and latest comments
    enriched_items = []
    for item in filtered_items:
        entrance_tx = Transaction.query.filter_by(item_id=item.id, action='ENTRANCE').order_by(Transaction.timestamp.asc()).first()
        exit_tx = Transaction.query.filter_by(item_id=item.id, action='EXIT').order_by(Transaction.timestamp.desc()).first()
        latest_tx = Transaction.query.filter_by(item_id=item.id).order_by(Transaction.timestamp.desc()).first()

        enriched_items.append({
            'obj': item,
            'entrance_date': entrance_tx.timestamp.strftime('%Y-%m-%d %H:%M') if entrance_tx else '-',
            'exit_date': exit_tx.timestamp.strftime('%Y-%m-%d %H:%M') if (exit_tx and item.status == 'EXITED') else '-',
            'latest_comment': latest_tx.comment if (latest_tx and latest_tx.comment) else '-'
        })

    all_categories = Category.query.all()
    all_properties = PropertyClient.query.all()
    all_transactions = Transaction.query.order_by(Transaction.timestamp.desc()).all()

    return render_template(
        'report.html', 
        items=enriched_items, 
        categories=all_categories, 
        properties=all_properties, 
        transactions=all_transactions,
        selected_model=selected_model,
        selected_property=selected_property,
        search_query=search_query
    )

@app.route('/edit_item/<int:item_id>', methods=['POST'])
@login_required
def edit_item(item_id):
    item = Item.query.get_or_404(item_id)
    
    new_serial = request.form.get('serial_number', '').strip()
    new_category_id = request.form.get('category_id')
    new_property_id = request.form.get('property_id')
    new_status = request.form.get('status')
    new_comment = request.form.get('comment', '').strip()

    # Ensure unique serial constraint if changed
    existing_item = Item.query.filter(Item.serial_number == new_serial, Item.id != item_id).first()
    if existing_item:
        flash(f'Error: Serial Number {new_serial} is already assigned to another item!')
        return redirect(url_for('report'))

    item.serial_number = new_serial
    if new_category_id and new_category_id.isdigit():
        item.category_id = int(new_category_id)
    
    item.property_id = int(new_property_id) if new_property_id and new_property_id.isdigit() else None
    if new_status in ['IN_STOCK', 'EXITED']:
        item.status = new_status

    # Update or insert a comment entry into transaction audit log
    latest_tx = Transaction.query.filter_by(item_id=item.id).order_by(Transaction.timestamp.desc()).first()
    if latest_tx:
        latest_tx.comment = new_comment
    else:
        new_tx = Transaction(item_id=item.id, user_id=current_user.id, action=item.status, comment=new_comment)
        db.session.add(new_tx)

    db.session.commit()
    flash(f'Device details for {new_serial} updated successfully!')
    return redirect(url_for('report'))

@app.route('/item_history/<int:item_id>')
@login_required
def item_history(item_id):
    item = Item.query.get_or_404(item_id)
    tx_list = Transaction.query.filter_by(item_id=item.id).order_by(Transaction.timestamp.desc()).all()
    
    history_data = []
    for tx in tx_list:
        history_data.append({
            'timestamp': tx.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'action': tx.action,
            'user': tx.user.username if tx.user else 'System',
            'comment': tx.comment or '-'
        })

    return jsonify({
        'serial_number': item.serial_number,
        'model': f"{item.category_rel.vendor} {item.category_rel.model}",
        'history': history_data
    })


@app.route('/reenter_item/<int:item_id>', methods=['POST'])
@login_required
def reenter_item(item_id):
    item = Item.query.get_or_404(item_id)
    comment = request.form.get('comment', 'Re-entered into warehouse stock').strip()

    item.status = 'IN_STOCK'
    
    # Record new ENTRANCE event in audit history
    new_tx = Transaction(
        item_id=item.id,
        user_id=current_user.id,
        action='ENTRANCE',
        comment=comment
    )
    db.session.add(new_tx)
    db.session.commit()

    flash(f'Item {item.serial_number} successfully re-entered into inventory stock!')
    return redirect(url_for('report'))
    
@app.route('/delete_item/<int:item_id>', methods=['POST'])
@login_required
def delete_item(item_id):
    item = Item.query.get_or_404(item_id)
    
    # Remove associated transaction history before deleting item
    Transaction.query.filter_by(item_id=item_id).delete()
    
    serial = item.serial_number
    db.session.delete(item)
    db.session.commit()
    
    flash(f'Item {serial} and its transaction history deleted successfully!')
    return redirect(url_for('report'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            hashed_pw = generate_password_hash('admin123', method='pbkdf2:sha256')
            db.session.add(User(username='admin', password=hashed_pw))
            db.session.commit()
            
    app.run(host='0.0.0.0', port=5000)
