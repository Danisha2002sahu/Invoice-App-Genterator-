from flask import Flask, render_template, request, redirect, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
import os
from io import BytesIO
from xhtml2pdf import pisa
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import urllib.parse

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///invoices.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB max
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = "vivayharry@gmail.com"     # Your Gmail
app.config['MAIL_PASSWORD'] = "pmig phbv sulu jgej"        # App password (not your Gmail password!)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

db = SQLAlchemy(app)
mail = Mail(app)

class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    client = db.Column(db.String(100))
    client_email = db.Column(db.String(120))
    mobile = db.Column(db.String(20))
    total = db.Column(db.Float)
    date = db.Column(db.String(10))
    due_date = db.Column(db.String(10))
    image = db.Column(db.String(120))
    items = db.relationship('InvoiceItem', backref='invoice', lazy=True)

class InvoiceItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    desc = db.Column(db.String(200))
    qty = db.Column(db.Integer)
    price = db.Column(db.Float)
    total = db.Column(db.Float)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/', methods=['GET', 'POST'])
def invoice_form():
    if request.method == 'POST':
        data = request.form
        items = []
        total = 0

        # Image upload logic
        image_file = request.files.get('image')
        image_filename = None
        if image_file and allowed_file(image_file.filename):
            image_filename = secure_filename(image_file.filename)
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], image_filename)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            image_file.save(image_path)

        for i in range(1, int(data['item_count']) + 1):
            desc = data.get(f'desc_{i}')
            qty = int(data.get(f'qty_{i}', 0))
            price = float(data.get(f'price_{i}', 0))
            total_item = qty * price
            items.append({'desc': desc, 'qty': qty, 'price': price, 'total': total_item})
            total += total_item
            
        invoice = Invoice(
            name=data['name'],
            client=data['client'],
            client_email=data.get('client_email', ''),
            mobile=data['mobile'],
            total=total,
            date=datetime.now().strftime("%d-%m-%Y"),
            due_date=(datetime.now() + timedelta(days=7)).strftime("%d-%m-%Y"),
            image=image_filename
        )
        db.session.add(invoice)
        db.session.commit()
        for item in items:
            invoice_item = InvoiceItem(
                desc=item['desc'],
                qty=item['qty'],
                price=item['price'],
                total=item['total'],
                invoice_id=invoice.id
            )
            db.session.add(invoice_item)
        db.session.commit()

        return render_template('invoice.html', data=data, items=items, total=total, submitted=True)
    return render_template('invoice.html', submitted=False)

@app.route('/all-invoices')
def all_invoices():
    search = request.args.get('search', '')
    if search:
        invoices = Invoice.query.filter(Invoice.client.ilike(f"%{search}%")).all()
    else:
        invoices = Invoice.query.all()
    return render_template('all_invoices.html', invoices=invoices, search=search)

@app.route('/invoice/<int:invoice_id>')
def invoice_detail(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    items = InvoiceItem.query.filter_by(invoice_id=invoice.id).all()
    return render_template('invoice_detail.html', invoice=invoice, items=items)

@app.route('/invoice/<int:invoice_id>/delete', methods=['POST'])
def delete_invoice(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    InvoiceItem.query.filter_by(invoice_id=invoice.id).delete()
    db.session.delete(invoice)
    db.session.commit()
    return redirect(url_for('all_invoices'))

@app.route('/invoice/<int:invoice_id>/edit', methods=['GET', 'POST'])
def edit_invoice(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    items = InvoiceItem.query.filter_by(invoice_id=invoice.id).all()
    if request.method == 'POST':
        invoice.name = request.form['name']
        invoice.client = request.form['client']
        db.session.commit()
        # Update items
        InvoiceItem.query.filter_by(invoice_id=invoice.id).delete()
        db.session.commit()
        total = 0
        for i in range(1, int(request.form['item_count']) + 1):
            desc = request.form.get(f'desc_{i}')
            qty = int(request.form.get(f'qty_{i}', 0))
            price = float(request.form.get(f'price_{i}', 0))
            total_item = qty * price
            total += total_item
            invoice_item = InvoiceItem(
                desc=desc,
                qty=qty,
                price=price,
                total=total_item,
                invoice_id=invoice.id
            )
            db.session.add(invoice_item)
        invoice.total = total
        db.session.commit()
        return redirect(url_for('invoice_detail', invoice_id=invoice.id))
    return render_template('edit_invoice.html', invoice=invoice, items=items)

def fetch_image(uri):
    """Helper function to fetch image data for PDF generation"""
    if uri.startswith('http'):
        return uri
    # Handle local files
    if uri.startswith('/static/'):
        path = os.path.join(app.root_path, uri.lstrip('/'))
    else:
        path = os.path.join(app.root_path, 'static', 'uploads', os.path.basename(uri))
    return path if os.path.exists(path) else None

@app.route('/invoice/<int:invoice_id>/pdf')
def invoice_pdf(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    items = InvoiceItem.query.filter_by(invoice_id=invoice.id).all()
    
    # Create HTML with absolute image paths
    if invoice.image:
        image_path = os.path.join(app.root_path, 'static', 'uploads', invoice.image)
        if os.path.exists(image_path):
            # Use file:// protocol for local files
            image_uri = 'file://' + urllib.parse.quote(image_path)
        else:
            image_uri = None
    else:
        image_uri = None
    
    html = render_template('invoice_pdf.html', 
                         invoice=invoice, 
                         items=items, 
                         image_uri=image_uri)
    
    result = BytesIO()
    
    # Configure PDF options
    pdf_options = {
        'page-size': 'A4',
        'margin-top': '0.5in',
        'margin-right': '0.5in',
        'margin-bottom': '0.5in',
        'margin-left': '0.5in',
        'encoding': 'UTF-8',
    }
    
    # Convert HTML to PDF with proper image handling
    pisa.CreatePDF(
        BytesIO(html.encode('utf-8')),
        dest=result,
        link_callback=fetch_image
    )
    
    result.seek(0)
    return send_file(result, download_name=f'invoice_{invoice.id}.pdf', as_attachment=True)

@app.route('/invoice/<int:invoice_id>/generate', methods=['GET', 'POST'])
def generate_invoice():
    return invoice_form()

@app.route('/invoice/<int:invoice_id>/send-email')
def send_invoice_email(invoice_id):
    try:
        # Get invoice details
        invoice = Invoice.query.get_or_404(invoice_id)
        items = InvoiceItem.query.filter_by(invoice_id=invoice.id).all()
        
        # Generate PDF
        html = render_template('invoice_pdf.html', invoice=invoice, items=items)
        pdf_buffer = BytesIO()
        pisa.CreatePDF(BytesIO(html.encode('utf-8')), dest=pdf_buffer)
        pdf_buffer.seek(0)
        
        # Create email
        msg = Message(
            subject=f'Invoice #{invoice.id} from Your Company',
            sender=app.config['MAIL_USERNAME'],
            recipients=[invoice.client_email] if hasattr(invoice, 'client_email') and invoice.client_email else ['recipient@example.com']
        )
        msg.body = f"""
        Dear {invoice.client},
        
        Please find attached the invoice #{invoice.id} for your reference.
        
        Total Amount: ₹{invoice.total:.2f}
        Due Date: {invoice.due_date}
        
        Thank you for your business!
        
        Best regards,
        Your Company Name
        """
        
        # Attach PDF
        msg.attach(
            f"invoice_{invoice.id}.pdf",
            "application/pdf",
            pdf_buffer.getvalue()
        )
        
        # Send email
        mail.send(msg)
        
        return redirect(url_for('invoice_detail', invoice_id=invoice.id, email_sent=True))
        
    except Exception as e:
        print(f"Error sending email: {str(e)}")
        return redirect(url_for('invoice_detail', invoice_id=invoice.id, email_error=True))

if __name__ == '__main__':
    os.chdir(r"d:\invoice app\invoice\invoice-generator-app")
    with app.app_context():
        db.create_all()
    app.run(debug=True)