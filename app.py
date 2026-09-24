import os
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from sqlalchemy import or_, text
import pandas as pd

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'warehouse.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- UPLOAD FOLDER CONFIGURATION ---
UPLOAD_FOLDER = os.path.join(app.root_path, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_attachment(file_obj):
    if file_obj and file_obj.filename != '' and allowed_file(file_obj.filename):
        ext = file_obj.filename.rsplit('.', 1)[1].lower()
        unique_name = f"{uuid.uuid4().hex[:10]}_{secure_filename(file_obj.filename)}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
        file_obj.save(file_path)
        return unique_name
    return None

# --- DATABASE & LOGIN INITIALIZATION ---
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def rome_now():
    return datetime.now(ZoneInfo("Europe/Rome"))

# --- MODELS ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    vendor = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(50), nullable=False)

class PropertyClient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    serial_number = db.Column(db.String(100), unique=True, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    property_id = db.Column(db.Integer, db.ForeignKey('property_client.id'), nullable=True)
    status = db.Column(db.String(20), default='IN_STOCK')

    category_rel = db.relationship('Category', backref=db.backref('items', lazy=True))
    owner_property = db.relationship('PropertyClient', backref=db.backref('items', lazy=True))

class Transaction(db.Model):
    __tablename__ = 'transaction'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action = db.Column(db.String(20), nullable=False)
    timestamp = db.Column(db.DateTime, default=rome_now)
    comment = db.Column(db.String(255), nullable=True)
    attachment = db.Column(db.String(255), nullable=True)

    item = db.relationship('Item', backref=db.backref('transactions', lazy=True))
    user = db.relationship('User', backref=db.backref('transactions', lazy=True))

# Auto-migrate DB schema
with app.app_context():
    db.create_all()
    try:
        db.session.execute(text("ALTER TABLE transaction ADD COLUMN attachment VARCHAR(255)"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    if not User.query.filter_by(username='admin').first():
        default_admin = User(username='admin', password=generate_password_hash('admin123'))
        db.session.add(default_admin)
        db.session.commit()

# --- ROUTES ---

@app.route('/')
@login_required
def index():
    categories = Category.query.all()
    
    category_counts = []
    for cat in categories:
        in_stock_cnt = Item.query.filter_by(category_id=cat.id, status='IN_STOCK').count()
        exited_cnt = Item.query.filter_by(category_id=cat.id, status='EXITED').count()
        category_counts.append({
            'vendor': cat.vendor,
            'name': cat.name,
            'model': cat.model,
            'in_stock': in_stock_cnt,
            'exited': exited_cnt
        })

    metrics = {
        'total_items': Item.query.count(),
        'total_in_stock': Item.query.filter_by(status='IN_STOCK').count(),
        'total_exited': Item.query.filter_by(status='EXITED').count(),
        'total_categories': len(categories)
    }

    recent_transactions = Transaction.query.order_by(Transaction.timestamp.desc()).limit(10).all()

    return render_template(
        'index.html',
        metrics=metrics,
        recent_transactions=recent_transactions,
        category_counts=category_counts
    )


@app.route('/uploads/<path:filename>')
@login_required
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password!')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))
@app.route('/transaction', methods=['GET', 'POST'])
@login_required
def transaction():
    if request.method == 'POST':
        action = request.form.get('action')
        serial_number = request.form.get('serial_number', '').strip()
        category_id = request.form.get('category_id')
        property_id = request.form.get('property_id')
        comment = request.form.get('comment', '').strip()
        attachment_file = request.files.get('attachment')
        custom_time_str = request.form.get('custom_timestamp')

        if not serial_number:
            flash('Error: Serial number is required!')
            return redirect(url_for('transaction'))

        # Parsing della data/ora personalizzata
        if custom_time_str:
            try:
                event_timestamp = datetime.strptime(custom_time_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                event_timestamp = rome_now()
        else:
            event_timestamp = rome_now()

        uploaded_filename = save_attachment(attachment_file)
        item = Item.query.filter_by(serial_number=serial_number).first()

        if action == 'ENTRANCE':
            if item and item.status == 'IN_STOCK':
                flash(f'Item {serial_number} is ALREADY IN STOCK!')
                return redirect(url_for('transaction'))
            
            if not item:
                if not category_id or not category_id.isdigit():
                    flash('Error: Model/Category selection required for new item!')
                    return redirect(url_for('transaction'))
                item = Item(serial_number=serial_number, category_id=int(category_id), status='IN_STOCK')
                db.session.add(item)
            else:
                item.status = 'IN_STOCK'
            
            if property_id and property_id.isdigit():
                item.property_id = int(property_id)

        elif action == 'EXIT':
            if not item or item.status == 'EXITED':
                flash(f'Error: Item {serial_number} is not in stock!')
                return redirect(url_for('transaction'))
            item.status = 'EXITED'

        tx = Transaction(
            item=item, 
            user_id=current_user.id, 
            action=action, 
            comment=comment,
            attachment=uploaded_filename,
            timestamp=event_timestamp  # Salva la data scelta dall'utente
        )
        db.session.add(tx)
        db.session.commit()

        flash(f'Movement logged for serial: {serial_number}')
        return redirect(url_for('transaction'))

    categories = Category.query.all()
    properties = PropertyClient.query.all()
    return render_template('log_transaction.html', categories=categories, properties=properties)



@app.route('/report')
@login_required
def report():
    selected_model = request.args.get('model_filter', '')
    selected_property = request.args.get('property_filter', '')
    search_query = request.args.get('search_query', '').strip()

    query = Item.query.outerjoin(Category).outerjoin(PropertyClient).outerjoin(Transaction)

    if selected_model:
        query = query.filter(Category.model == selected_model)
    if selected_property and selected_property.isdigit():
        query = query.filter(Item.property_id == int(selected_property))

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

    filtered_items = query.distinct().all()

    enriched_items = []
    for item in filtered_items:
        entrance_tx = Transaction.query.filter_by(item_id=item.id, action='ENTRANCE').order_by(Transaction.timestamp.asc()).first()
        exit_tx = Transaction.query.filter_by(item_id=item.id, action='EXIT').order_by(Transaction.timestamp.desc()).first()
        latest_tx = Transaction.query.filter_by(item_id=item.id).order_by(Transaction.timestamp.desc()).first()

        enriched_items.append({
            'obj': item,
            'entrance_date': entrance_tx.timestamp.strftime('%Y-%m-%d %H:%M') if entrance_tx else '-',
            'exit_date': exit_tx.timestamp.strftime('%Y-%m-%d %H:%M') if (exit_tx and item.status == 'EXITED') else '-',
            'latest_comment': latest_tx.comment if (latest_tx and latest_tx.comment) else '-',
            'attachment': latest_tx.attachment if (latest_tx and latest_tx.attachment) else None
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
            'comment': tx.comment or '-',
            'attachment': tx.attachment or None
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

@app.route('/quick_exit/<int:item_id>', methods=['POST'])
@login_required
def quick_exit(item_id):
    item = Item.query.get_or_404(item_id)
    comment = request.form.get('comment', '').strip()
    item.status = 'EXITED'
    db.session.add(Transaction(item_id=item.id, user_id=current_user.id, action='EXIT', comment=comment or 'Quick Exit from Report page'))
    db.session.commit()
    flash(f'Device {item.serial_number} marked as EXITED.')
    return redirect(url_for('report'))

@app.route('/edit_item/<int:item_id>', methods=['POST'])
@login_required
def edit_item(item_id):
    item = Item.query.get_or_404(item_id)
    new_serial = request.form.get('serial_number', '').strip()
    category_id = request.form.get('category_id')
    property_id = request.form.get('property_id')
    status = request.form.get('status')
    comment = request.form.get('comment', '').strip()
    custom_time_str = request.form.get('custom_timestamp')

    if new_serial and new_serial != item.serial_number:
        if Item.query.filter_by(serial_number=new_serial).first():
            flash(f'Error: Serial number {new_serial} already exists!')
            return redirect(url_for('report'))
        item.serial_number = new_serial

    if category_id and category_id.isdigit():
        item.category_id = int(category_id)

    item.property_id = int(property_id) if (property_id and property_id.isdigit()) else None
    item.status = status

    latest_tx = Transaction.query.filter_by(item_id=item.id).order_by(Transaction.timestamp.desc()).first()
    if latest_tx:
        if comment:
            latest_tx.comment = comment
        if custom_time_str:
            try:
                latest_tx.timestamp = datetime.strptime(custom_time_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                pass

    db.session.commit()
    flash(f'Device details for {item.serial_number} updated successfully!')
    return redirect(url_for('report'))

@app.route('/delete_item/<int:item_id>', methods=['POST'])
@login_required
def delete_item(item_id):
    item = Item.query.get_or_404(item_id)
    serial = item.serial_number
    Transaction.query.filter_by(item_id=item.id).delete()
    db.session.delete(item)
    db.session.commit()
    flash(f'Item {serial} deleted permanently.')
    return redirect(url_for('report'))
    
@app.route('/manage', methods=['GET', 'POST'])
@login_required
def manage_metadata():
    if request.method == 'POST':
        form_type = request.form.get('form_type')
        
        if form_type == 'category':
            name = request.form.get('name', '').strip()
            vendor = request.form.get('vendor', '').strip()
            model = request.form.get('model', '').strip()
            if name and vendor and model:
                db.session.add(Category(name=name, vendor=vendor, model=model))
                db.session.commit()
                flash('Category added successfully!')

        elif form_type == 'property':
            prop_name = request.form.get('property_name', '').strip()
            if prop_name:
                db.session.add(PropertyClient(name=prop_name))
                db.session.commit()
                flash('Property / Client added successfully!')

        elif form_type == 'user':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '').strip()
            if username and password:
                if User.query.filter_by(username=username).first():
                    flash('User already exists!')
                else:
                    new_u = User(username=username, password=generate_password_hash(password))
                    db.session.add(new_u)
                    db.session.commit()
                    flash(f'User {username} created!')
                    
        return redirect(url_for('manage_metadata'))

    categories = Category.query.all()
    properties = PropertyClient.query.all()
    users = User.query.all()
    return render_template('manage_metadata.html', categories=categories, properties=properties, users=users)


@app.route('/bulk_import', methods=['GET', 'POST'])
@login_required
def bulk_import():
    if request.method == 'POST':
        category_id = request.form.get('category_id')
        property_id = request.form.get('property_id')
        file = request.files.get('file')

        if not category_id or not file:
            flash('Category and file are required!')
            return redirect(url_for('bulk_import'))

        filename = file.filename.lower()
        serials = []

        try:
            if filename.endswith('.csv') or filename.endswith('.txt'):
                df = pd.read_csv(file, header=None)
                serials = df[0].dropna().astype(str).str.strip().tolist()
            elif filename.endswith('.xlsx') or filename.endswith('.xls'):
                df = pd.read_excel(file, header=None)
                serials = df[0].dropna().astype(str).str.strip().tolist()
            else:
                flash('Unsupported file format!')
                return redirect(url_for('bulk_import'))
        except Exception as e:
            flash(f'Error processing file: {str(e)}')
            return redirect(url_for('bulk_import'))

        imported_count = 0
        for sn in serials:
            if not sn or sn.lower() in ['serial number', 'sn', 'serial']:
                continue

            item = Item.query.filter_by(serial_number=sn).first()
            if not item:
                item = Item(serial_number=sn, category_id=int(category_id), status='IN_STOCK')
                if property_id and property_id.isdigit():
                    item.property_id = int(property_id)
                db.session.add(item)
                db.session.flush()
                db.session.add(Transaction(item_id=item.id, user_id=current_user.id, action='ENTRANCE', comment='Bulk File Import'))
                imported_count += 1

        db.session.commit()
        flash(f'Successfully imported {imported_count} new serials!')
        return redirect(url_for('report'))

    categories = Category.query.all()
    properties = PropertyClient.query.all()
    return render_template('bulk_import.html', categories=categories, properties=properties)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
