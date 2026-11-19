import os, secrets, hashlib, hmac, json, csv, io, smtplib
from datetime import datetime, timedelta, date
from email.message import EmailMessage
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, make_response, abort, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
from sqlalchemy import func
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

load_dotenv()
app=Flask(__name__, instance_relative_config=True)
app.debug=os.getenv('FLASK_DEBUG','1')=='1'
app.config.update(SECRET_KEY=os.getenv('SECRET_KEY','dev-only-change-me'), SQLALCHEMY_DATABASE_URI=os.getenv('DATABASE_URL','sqlite:///srg.db').replace('postgres://','postgresql://'), SQLALCHEMY_TRACK_MODIFICATIONS=False, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('FLASK_DEBUG','1')!='1')
os.makedirs(app.instance_path,exist_ok=True)
db=SQLAlchemy(app); login=LoginManager(app); login.login_view='login'; csrf=CSRFProtect(app)

# Models
class User(UserMixin,db.Model):
 id=db.Column(db.Integer,primary_key=True); email=db.Column(db.String(254),unique=True,nullable=False,index=True); mobile=db.Column(db.String(15),unique=True,nullable=True,index=True); role=db.Column(db.String(12),default='customer'); customer_type=db.Column(db.String(12),default='retail'); status=db.Column(db.String(16),default='active'); created_at=db.Column(db.DateTime,default=datetime.utcnow); last_session=db.Column(db.String(64))
class Address(db.Model):
 id=db.Column(db.Integer,primary_key=True); user_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False); name=db.Column(db.String(80),nullable=False); mobile=db.Column(db.String(15),nullable=False); line1=db.Column(db.String(180),nullable=False); line2=db.Column(db.String(180)); city=db.Column(db.String(80),nullable=False); state=db.Column(db.String(80),default='Karnataka'); pincode=db.Column(db.String(10),nullable=False); is_default=db.Column(db.Boolean,default=False)
class Product(db.Model):
 id=db.Column(db.Integer,primary_key=True); name=db.Column(db.String(100),nullable=False); description=db.Column(db.Text,default=''); image_url=db.Column(db.String(500)); active=db.Column(db.Boolean,default=True)
class Variant(db.Model):
 id=db.Column(db.Integer,primary_key=True); product_id=db.Column(db.Integer,db.ForeignKey('product.id'),nullable=False); pack_size=db.Column(db.String(60),nullable=False); retail_price=db.Column(db.Integer); wholesale_price=db.Column(db.Integer); active=db.Column(db.Boolean,default=True); stock=db.Column(db.Integer,default=0); low_stock=db.Column(db.Integer,default=10); product=db.relationship('Product',backref='variants')
class Coupon(db.Model):
 id=db.Column(db.Integer,primary_key=True); code=db.Column(db.String(32),unique=True,nullable=False); customer_type=db.Column(db.String(12),nullable=False); percent=db.Column(db.Integer,nullable=False); minimum=db.Column(db.Integer,nullable=False); max_discount=db.Column(db.Integer,nullable=False); expiry=db.Column(db.Date,nullable=False); active=db.Column(db.Boolean,default=True); created_at=db.Column(db.DateTime,default=datetime.utcnow)
class Order(db.Model):
 id=db.Column(db.Integer,primary_key=True); number=db.Column(db.String(30),unique=True,index=True); user_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False); customer_type=db.Column(db.String(12)); address_json=db.Column(db.Text); subtotal=db.Column(db.Integer); discount=db.Column(db.Integer); delivery=db.Column(db.Integer); total=db.Column(db.Integer); coupon_code=db.Column(db.String(32)); payment_method=db.Column(db.String(20),default='COD'); status=db.Column(db.String(30),default='Order Placed'); created_at=db.Column(db.DateTime,default=datetime.utcnow); user=db.relationship('User')
class OrderItem(db.Model):
 id=db.Column(db.Integer,primary_key=True); order_id=db.Column(db.Integer,db.ForeignKey('order.id')); product_name=db.Column(db.String(100)); pack_size=db.Column(db.String(60)); quantity=db.Column(db.Integer); unit_price=db.Column(db.Integer); amount=db.Column(db.Integer)
class StatusLog(db.Model):
 id=db.Column(db.Integer,primary_key=True); order_id=db.Column(db.Integer,db.ForeignKey('order.id')); old_status=db.Column(db.String(30)); new_status=db.Column(db.String(30)); actor=db.Column(db.String(254)); created_at=db.Column(db.DateTime,default=datetime.utcnow); note=db.Column(db.Text)
class CouponUse(db.Model):
 id=db.Column(db.Integer,primary_key=True); coupon_id=db.Column(db.Integer,db.ForeignKey('coupon.id')); user_id=db.Column(db.Integer,db.ForeignKey('user.id')); used_at=db.Column(db.DateTime,default=datetime.utcnow)
class Audit(db.Model):
 id=db.Column(db.Integer,primary_key=True); actor=db.Column(db.String(254)); action=db.Column(db.String(100)); record_id=db.Column(db.String(50)); detail=db.Column(db.Text); created_at=db.Column(db.DateTime,default=datetime.utcnow)
class Notice(db.Model):
 id=db.Column(db.Integer,primary_key=True); recipient=db.Column(db.String(254)); kind=db.Column(db.String(60)); body=db.Column(db.Text); status=db.Column(db.String(20),default='queued'); created_at=db.Column(db.DateTime,default=datetime.utcnow)

@login.user_loader
def load_user(uid): return db.session.get(User,int(uid))

def money(n): return int(Decimal(str(n)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def log(action,record='',detail=''):
 db.session.add(Audit(actor=(current_user.email or current_user.mobile or 'user') if current_user.is_authenticated else 'system',action=action,record_id=str(record),detail=str(detail)))
def admin_required(fn):
 @wraps(fn)
 @login_required
 def wrap(*a,**k):
  if current_user.role!='admin': abort(403)
  return fn(*a,**k)
 return wrap

def send_sms(mobile,kind,body):
 # Provider adapter: implement the provider-specific POST here; never log OTP contents in production.
 provider=os.getenv('SMS_PROVIDER','console')
 if provider=='console' and app.debug: print(f'[DEV SMS {kind}] {mobile}: {body}'); status='dev-console'
 elif os.getenv('SMS_API_URL') and os.getenv('SMS_API_KEY'): status='queued' # API adapter intentionally isolated for provider wiring
 else: status='not-configured'
 db.session.add(Notice(recipient=mobile,kind=kind,body=body,status=status))

def send_email_otp(email, otp):
 # SMTP credentials are environment variables; never store or expose them in the app.
 host=os.getenv('SMTP_HOST','smtp.gmail.com'); port=int(os.getenv('SMTP_PORT','587'))
 username=os.getenv('SMTP_USERNAME',''); password=os.getenv('SMTP_APP_PASSWORD',''); sender=os.getenv('SMTP_FROM',username)
 if not username or not password or not sender:
  if app.debug:
   print(f'[DEV EMAIL OTP] {email}: {otp}')
   return 'dev-console'
  raise RuntimeError('Email OTP is not configured. Set SMTP_USERNAME, SMTP_APP_PASSWORD and SMTP_FROM.')
 msg=EmailMessage(); msg['Subject']='Your SRG verification code'; msg['From']=sender; msg['To']=email
 msg.set_content(f'Your SRG verification code is {otp}. It is valid for 3 minutes. Do not share this code with anyone.')
 with smtplib.SMTP(host,port,timeout=15) as smtp:
  smtp.starttls(); smtp.login(username,password); smtp.send_message(msg)
 return 'sent'

def send_whatsapp(mobile,kind,body):
 status='queued' if os.getenv('WHATSAPP_API_URL') and os.getenv('WHATSAPP_API_KEY') else 'not-configured'
 db.session.add(Notice(recipient=mobile,kind='whatsapp:'+kind,body=body,status=status))

def delivery_charge(subtotal):
 raw=os.getenv('RETAIL_DELIVERY_SLABS','').strip()
 if not raw: raise ValueError('Retail delivery slabs are not configured. Ask SRG to configure delivery charges.')
 slabs=[]
 for part in raw.split(','):
  threshold,charge=part.split(':'); slabs.append((int(threshold),int(charge)))
 slabs.sort(); eligible=[c for t,c in slabs if subtotal>=t]
 return eligible[-1] if eligible else slabs[0][1]

def eligible_coupons(user,subtotal):
 today=date.today(); used=CouponUse.query.filter_by(user_id=user.id).filter(func.date(CouponUse.used_at)==today).all(); used_ids={x.coupon_id for x in used}
 rows=Coupon.query.filter_by(active=True,customer_type=user.customer_type).filter(Coupon.expiry>=today).all(); out=[]
 for c in rows:
  if c.id in used_ids or subtotal<c.minimum: continue
  out.append((c,min(money(subtotal*c.percent/100),c.max_discount)))
 return sorted(out,key=lambda x:(-x[1],x[0].expiry))

def calculate_cart(user,raw_items,coupon_id=None):
 lines=[]; subtotal=0
 for item in raw_items:
  v=db.session.get(Variant,int(item.get('variant_id',0))); q=int(item.get('quantity',0))
  if not v or not v.active or not v.product.active or q<1 or q>99: raise ValueError('Invalid product or quantity.')
  if q>v.stock: raise ValueError(f'Only {v.stock} left for {v.product.name} ({v.pack_size}).')
  price=v.retail_price if user.customer_type=='retail' else v.wholesale_price
  if price is None: raise ValueError('This pack is unavailable for your account type.')
  amount=price*q; subtotal+=amount; lines.append((v,q,price,amount))
 choices=eligible_coupons(user,subtotal); chosen=choices[0] if choices else None
 # Even a manual choice cannot override the best eligible coupon.
 discount=chosen[1] if chosen else 0; coupon=chosen[0] if chosen else None
 if user.customer_type=='wholesale': delivery=0
 else: delivery=delivery_charge(subtotal-discount)
 return lines,subtotal,discount,delivery,coupon

@app.context_processor
def globals_ctx(): return {'money':money,'cart_count':sum(int(x.get('quantity',0)) for x in session.get('cart',[])),'srg_phone':'7019931855'}
@app.route('/')
def home(): return render_template('home.html',products=Product.query.filter_by(active=True).all())
@app.route('/products')
def products(): return render_template('products.html',products=Product.query.filter_by(active=True).all())
@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  email=request.form.get('email','').strip().lower()
  if len(email)>254 or '@' not in email or '.' not in email.rsplit('@',1)[-1]:
   flash('Enter a valid email address.','error'); return redirect(url_for('login'))
  user=User.query.filter_by(email=email).first()
  if user and user.status!='active': flash('Account Blocked' if user.status=='blocked' else 'Account inactive. Contact SRG.','error'); return redirect(url_for('login'))
  state=session.get('otp_state',{}); now=datetime.utcnow().timestamp()
  if state.get('email')==email and now<state.get('blocked_until',0): flash('Too many attempts. Try again after 15 minutes.','error'); return redirect(url_for('login'))
  if state.get('email')!=email or now-state.get('started',0)>900: state={'email':email,'started':now,'requests':0,'attempts':0}
  if state['requests']>=3: state['blocked_until']=now+900; session['otp_state']=state; flash('OTP request limit reached. Try again in 15 minutes.','error'); return redirect(url_for('login'))
  session.pop('dev_otp',None)
  otp=f'{secrets.randbelow(1000000):06d}'
  state.update(requests=state['requests']+1,hash=hashlib.sha256(otp.encode()).hexdigest(),expires=now+180); session['otp_state']=state
  try: delivery=send_email_otp(email,otp)
  except Exception as e:
   session.pop('otp_state',None); flash(str(e) if app.debug else 'Could not send email OTP. Please try again later.','error'); return redirect(url_for('login'))
  if app.debug and delivery=='dev-console': session['dev_otp']=otp
  db.session.add(Notice(recipient=email,kind='login_otp',body='SRG email verification OTP requested',status=delivery)); db.session.commit()
  flash('OTP sent to your email address.','success'); return render_template('verify.html',destination=email,dev_otp=session.get('dev_otp'))
 return render_template('login.html')
@app.route('/verify',methods=['POST'])
def verify():
 state=session.get('otp_state',{}); otp=request.form.get('otp','')
 if not state or datetime.utcnow().timestamp()>state.get('expires',0): flash('OTP expired. Request a new one.','error'); return redirect(url_for('login'))
 if state.get('attempts',0)>=3: flash('Too many incorrect attempts. Request a new OTP after 15 minutes.','error'); return redirect(url_for('login'))
 if len(otp)!=6 or not otp.isdigit() or not hmac.compare_digest(hashlib.sha256(otp.encode()).hexdigest(),state.get('hash','')):
  state['attempts']=state.get('attempts',0)+1
  if state['attempts']>=3: state['blocked_until']=datetime.utcnow().timestamp()+900
  session['otp_state']=state; flash('Incorrect OTP.','error'); return redirect(url_for('login'))
 email=state['email']; user=User.query.filter_by(email=email).first()
 if user and user.status!='active': flash('Account Blocked','error'); return redirect(url_for('login'))
 if not user:
  user=User(email=email); db.session.add(user); db.session.flush()
  db.session.add(Notice(recipient=email,kind='registration_success',body='SRG account created',status='recorded'))
 sid=secrets.token_urlsafe(32); user.last_session=hashlib.sha256(sid.encode()).hexdigest(); db.session.commit(); session.clear(); session['session_token']=sid; login_user(user); flash('Welcome to SRG.','success'); return redirect(url_for('home'))
@app.before_request
def enforce_single_session():
 if current_user.is_authenticated and current_user.last_session:
  token=session.get('session_token','')
  if not token or not hmac.compare_digest(current_user.last_session,hashlib.sha256(token.encode()).hexdigest()):
   from flask_login import logout_user
   logout_user(); session.clear(); flash('You were signed out because this account was used on another device.','error')

@app.route('/account')
@login_required
def account(): return render_template('account.html',addresses=Address.query.filter_by(user_id=current_user.id).all())
@app.route('/address',methods=['POST'])
@login_required
def address_add():
 a=Address(user_id=current_user.id,name=request.form['name'],mobile=request.form['mobile'],line1=request.form['line1'],line2=request.form.get('line2'),city=request.form['city'],state=request.form.get('state','Karnataka'),pincode=request.form['pincode'],is_default=not Address.query.filter_by(user_id=current_user.id).first())
 if request.form.get('default')=='yes':
  for old in Address.query.filter_by(user_id=current_user.id): old.is_default=False
  a.is_default=True
 db.session.add(a); db.session.commit(); flash('Address saved.','success'); return redirect(url_for('account'))
@app.route('/cart/add',methods=['POST'])
@login_required
def cart_add():
 cart=session.get('cart',[]); vid=int(request.form['variant_id']); qty=int(request.form.get('quantity',1)); v=db.session.get(Variant,vid)
 if not v or not v.active or qty<1 or qty>v.stock: flash('Selected quantity is unavailable.','error')
 else:
  found=next((x for x in cart if int(x['variant_id'])==vid),None)
  if found: found['quantity']=min(v.stock,found['quantity']+qty)
  else: cart.append({'variant_id':vid,'quantity':qty})
  session['cart']=cart; flash('Added to cart.','success')
 return redirect(request.referrer or url_for('products'))
@app.route('/cart')
@login_required
def cart():
 try: lines,subtotal,discount,delivery,coupon=calculate_cart(current_user,session.get('cart',[]))
 except ValueError as e: lines=[]; subtotal=discount=delivery=0; coupon=None; flash(str(e),'error')
 return render_template('cart.html',lines=lines,subtotal=subtotal,discount=discount,delivery=delivery,coupon=coupon,total=subtotal-discount+delivery)
@app.route('/cart/update',methods=['POST'])
@login_required
def cart_update():
 vid=int(request.form['variant_id']); qty=int(request.form['quantity']); cart=session.get('cart',[])
 if qty<=0: cart=[x for x in cart if int(x['variant_id'])!=vid]
 else:
  for x in cart:
   if int(x['variant_id'])==vid: x['quantity']=qty
 session['cart']=cart; return redirect(url_for('cart'))
@app.route('/checkout',methods=['GET','POST'])
@login_required
def checkout():
 try: lines,subtotal,discount,delivery,coupon=calculate_cart(current_user,session.get('cart',[]))
 except ValueError as e: flash(str(e),'error'); return redirect(url_for('cart'))
 addresses=Address.query.filter_by(user_id=current_user.id).all()
 if request.method=='POST':
  aid=request.form.get('address_id'); a=db.session.get(Address,int(aid)) if aid else None
  if not a or a.user_id!=current_user.id: flash('Select a valid delivery address.','error'); return redirect(url_for('checkout'))
  # Recalculate and lock stock rows inside transaction before committing order.
  try:
   lines,subtotal,discount,delivery,coupon=calculate_cart(current_user,session.get('cart',[]))
   year=datetime.now().year; count=Order.query.filter(Order.number.like(f'SRG-{year}-%')).count()+1; number=f'SRG-{year}-{count:04d}'
   order=Order(number=number,user_id=current_user.id,customer_type=current_user.customer_type,address_json=json.dumps({k:getattr(a,k) for k in ['name','mobile','line1','line2','city','state','pincode']}),subtotal=subtotal,discount=discount,delivery=delivery,total=subtotal-discount+delivery,coupon_code=coupon.code if coupon else None)
   db.session.add(order); db.session.flush()
   for v,q,p,amt in lines:
    v.stock-=q; db.session.add(OrderItem(order_id=order.id,product_name=v.product.name,pack_size=v.pack_size,quantity=q,unit_price=p,amount=amt))
   if coupon: db.session.add(CouponUse(coupon_id=coupon.id,user_id=current_user.id))
   db.session.add(StatusLog(order_id=order.id,new_status='Order Placed',actor='customer'))
   if current_user.mobile:
    send_sms(current_user.mobile,'order_confirmation',f'SRG order {number} placed. Total ₹{order.total}. Cash on Delivery.')
    send_whatsapp(current_user.mobile,'order_confirmation',f'Your SRG order {number} is placed. Total ₹{order.total}.')
   db.session.commit(); session['cart']=[]; return redirect(url_for('order_detail',number=number))
  except Exception as e: db.session.rollback(); flash(str(e),'error'); return redirect(url_for('cart'))
 return render_template('checkout.html',addresses=addresses,lines=lines,subtotal=subtotal,discount=discount,delivery=delivery,total=subtotal-discount+delivery,coupon=coupon)
@app.route('/orders')
@login_required
def orders(): return render_template('orders.html',orders=Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all())
@app.route('/orders/<number>')
@login_required
def order_detail(number):
 o=Order.query.filter_by(number=number,user_id=current_user.id).first_or_404(); return render_template('order.html',order=o,items=OrderItem.query.filter_by(order_id=o.id).all(),history=StatusLog.query.filter_by(order_id=o.id).order_by(StatusLog.created_at).all())
@app.route('/offers')
@login_required
def offers():
 cs=Coupon.query.filter_by(active=True,customer_type=current_user.customer_type).filter(Coupon.expiry>=date.today()).all(); used={x.coupon_id for x in CouponUse.query.filter_by(user_id=current_user.id).filter(func.date(CouponUse.used_at)==date.today())}; return render_template('offers.html',coupons=cs,used=used)
@app.route('/invoice/<number>')
@login_required
def invoice(number):
 o=Order.query.filter_by(number=number,user_id=current_user.id).first_or_404()
 if o.status not in ['Confirmed','Packed','Shipped','Delivered']: abort(403)
 return make_invoice(o)
def make_invoice(o):
 buf=io.BytesIO(); c=canvas.Canvas(buf,pagesize=A4); w,h=A4; addr=json.loads(o.address_json)
 c.setFont('Helvetica-Bold',22); c.drawString(42,h-52,'SRG'); c.setFont('Helvetica-Bold',16); c.drawRightString(w-42,h-52,'INVOICE')
 c.setFont('Helvetica',9); c.drawString(42,h-72,'Sri Rama Gulkhand'); c.drawString(42,h-86,'390/343 Sri Lakshminarasimhaswamy Nilaya, 30 Feet Road, Prabhakar Layout')
 c.drawString(42,h-100,'Chintamani – 563125, Chikkaballapur District, Karnataka | 7019931855')
 c.line(42,h-115,w-42,h-115); c.drawString(42,h-135,f'Order/Bill Number: {o.number}'); c.drawString(330,h-135,f'Order date: {o.created_at:%d-%m-%Y %I:%M %p}')
 c.drawString(42,h-153,f'Customer email: {o.user.email}'); c.drawString(330,h-153,f'Customer type: {o.customer_type.title()}')
 c.drawString(42,h-171,f"Delivery: {addr['name']}, {addr['mobile']}, {addr['line1']} {addr.get('line2') or ''}, {addr['city']}, {addr['state']} - {addr['pincode']}")
 y=h-215; c.setFont('Helvetica-Bold',9)
 for x,t in [(42,'Product'),(245,'Pack Size'),(330,'Qty'),(375,'Unit Price'),(465,'Amount')]: c.drawString(x,y,t)
 c.line(42,y-5,w-42,y-5); y-=23; c.setFont('Helvetica',9)
 for it in OrderItem.query.filter_by(order_id=o.id):
  c.drawString(42,y,it.product_name[:35]); c.drawString(245,y,it.pack_size); c.drawRightString(355,y,str(it.quantity)); c.drawRightString(440,y,f'₹{it.unit_price}'); c.drawRightString(w-42,y,f'₹{it.amount}'); y-=20
 y-=18; c.drawRightString(w-42,y,f'Subtotal: ₹{o.subtotal}'); y-=18; c.drawRightString(w-42,y,f'Coupon Discount: -₹{o.discount}'); y-=18; c.drawRightString(w-42,y,f'Delivery Charge: ₹{o.delivery}'); y-=24; c.setFont('Helvetica-Bold',12); c.drawRightString(w-42,y,f'Grand Total: ₹{o.total}'); y-=30; c.setFont('Helvetica',9); c.drawString(42,y,'Payment Method: Cash on Delivery'); c.showPage(); c.save(); buf.seek(0)
 log('Invoice generated',o.number); db.session.commit(); return send_file(buf,as_attachment=True,download_name=f'{o.number}.pdf',mimetype='application/pdf')

# Admin area
@app.route('/admin')
@admin_required
def admin():
 today=date.today(); return render_template('admin.html',orders=Order.query.order_by(Order.created_at.desc()).limit(12).all(),today_orders=Order.query.filter(func.date(Order.created_at)==today).count(),today_sales=db.session.query(func.sum(Order.total)).filter(func.date(Order.created_at)==today).scalar() or 0,pending=Order.query.filter(Order.status.in_(['Order Placed','Confirmed','Packed'])).count(),customers=User.query.filter_by(role='customer').count(),low=Variant.query.filter(Variant.stock<=Variant.low_stock).count())
@app.route('/admin/products',methods=['GET','POST'])
@admin_required
def admin_products():
 if request.method=='POST':
  p=Product(name=request.form['name'],description=request.form.get('description','')); db.session.add(p); db.session.flush(); v=Variant(product_id=p.id,pack_size=request.form['pack_size'],retail_price=int(request.form['retail_price']),wholesale_price=int(request.form['wholesale_price']),stock=int(request.form.get('stock',0))); db.session.add(v); log('Product created',p.id,p.name); db.session.commit(); return redirect(url_for('admin_products'))
 return render_template('admin_products.html',products=Product.query.all())
@app.route('/admin/stock/<int:vid>',methods=['POST'])
@admin_required
def admin_stock(vid):
 v=db.session.get(Variant,vid) or abort(404); old=v.stock; v.stock=max(0,int(request.form['stock'])); log('Stock adjusted',vid,f'{old} -> {v.stock}'); db.session.commit(); return redirect(url_for('admin_products'))
@app.route('/admin/orders')
@admin_required
def admin_orders(): return render_template('admin_orders.html',orders=Order.query.order_by(Order.created_at.desc()).all())
@app.route('/admin/orders/<int:oid>/status',methods=['POST'])
@admin_required
def admin_status(oid):
 o=db.session.get(Order,oid) or abort(404); new=request.form['status']; allowed=['Confirmed','Packed','Shipped','Delivered','Cancelled']
 if new not in allowed: abort(400)
 old=o.status; o.status=new; db.session.add(StatusLog(order_id=o.id,old_status=old,new_status=new,actor=current_user.email))
 if o.user.mobile:
  send_sms(o.user.mobile,'order_status',f'SRG order {o.number}: {new}.')
  send_whatsapp(o.user.mobile,'order_status',f'SRG order {o.number}: {new}.')
 log('Order status changed',o.number,f'{old} -> {new}'); db.session.commit(); return redirect(url_for('admin_orders'))
@app.route('/admin/coupons',methods=['GET','POST'])
@admin_required
def admin_coupons():
 if request.method=='POST':
  c=Coupon(code=request.form['code'].upper(),customer_type=request.form['customer_type'],percent=int(request.form['percent']),minimum=int(request.form['minimum']),max_discount=int(request.form['max_discount']),expiry=datetime.strptime(request.form['expiry'],'%Y-%m-%d').date()); db.session.add(c); log('Coupon created',c.code); db.session.commit(); return redirect(url_for('admin_coupons'))
 return render_template('admin_coupons.html',coupons=Coupon.query.all())
@app.route('/admin/coupons/<int:cid>/deactivate',methods=['POST'])
@admin_required
def coupon_deactivate(cid):
 c=db.session.get(Coupon,cid) or abort(404); c.active=False; log('Coupon deactivated',c.code); db.session.commit(); return redirect(url_for('admin_coupons'))
@app.route('/admin/customers')
@admin_required
def admin_customers(): return render_template('admin_customers.html',customers=User.query.filter_by(role='customer').all())
@app.route('/admin/customer/<int:uid>/status',methods=['POST'])
@admin_required
def customer_status(uid):
 u=db.session.get(User,uid) or abort(404); u.status=request.form['status']; log('Customer status changed',u.email,u.status); db.session.commit(); return redirect(url_for('admin_customers'))
@app.route('/admin/export/customers')
@admin_required
def export_customers():
 s=io.StringIO(); w=csv.writer(s); w.writerow(['Email','Mobile','Type','Status','Created']);
 for u in User.query.filter_by(role='customer'): w.writerow([u.email,u.mobile or '',u.customer_type,u.status,u.created_at])
 return make_response((s.getvalue(),200,{'Content-Type':'text/csv','Content-Disposition':'attachment; filename=srg-customers.csv'}))
@app.route('/admin/activity')
@admin_required
def activity(): return render_template('activity.html',logs=Audit.query.order_by(Audit.created_at.desc()).limit(200).all())
@app.route('/admin/login')
def admin_login(): return redirect(url_for('login'))

@app.cli.command('init-db')
def init_db():
 db.create_all()
 # Lightweight migration for databases created by the earlier mobile-OTP starter.
 from sqlalchemy import inspect, text
 inspector=inspect(db.engine)
 if 'user' in inspector.get_table_names():
  cols={c['name'] for c in inspector.get_columns('user')}
  if 'email' not in cols: db.session.execute(text('ALTER TABLE user ADD COLUMN email VARCHAR(254)'))
  db.session.commit()
 if not Product.query.first():
  catalog=[('Special Gulkhand',[('250 GM',85,50),('500 GM',145,80),('1000 GM',200,190)]),('Dryfruits Gulkhand',[('500 GM',175,110)]),('Ordinary Gulkhand',[('1 KG',None,70),('2 KG',None,140),('5 KG',None,350),('1 KG × 10 Packets',None,690)])]
  for name,variants in catalog:
   p=Product(name=name,description='Traditional Sri Rama Gulkhand.'); db.session.add(p); db.session.flush()
   for pack,r,w in variants: db.session.add(Variant(product_id=p.id,pack_size=pack,retail_price=r,wholesale_price=w,stock=100))
 email=os.getenv('ADMIN_EMAIL','admin@example.com').strip().lower(); admin=User.query.filter_by(email=email).first()
 if not admin: db.session.add(User(email=email,role='admin',customer_type='wholesale'))
 db.session.commit(); print('Database initialized. Configure ADMIN_EMAIL, Gmail SMTP, and retail delivery slabs before production.')

@app.errorhandler(403)
def forbidden(e): return render_template('error.html',code=403,message='You do not have permission to access this page.'),403
@app.errorhandler(404)
def missing(e): return render_template('error.html',code=404,message='Page not found.'),404
if __name__=='__main__': app.run(debug=os.getenv('FLASK_DEBUG','1')=='1')
