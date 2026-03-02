# =================================================================
# CREDIFUERZA CLOUD v14.0 - SISTEMA PROFESIONAL DE MICROFINANZAS
# =================================================================
# Autor: Gemini para CrediFuerza Enterprise
# Objetivo: Gestión de Préstamos, Cobros y Capital en la Nube
# =================================================================

import os
import psycopg2
from psycopg2 import extras
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, session, url_for, flash

app = Flask(__name__)
# Configuración de Seguridad
app.secret_key = os.environ.get('SECRET_KEY', 'llave_maestra_2026_pro_v14')

# URL de conexión a Supabase (Cámbiala por la tuya con tu password real)
DATABASE_URL = "postgresql://postgres:TU_PASSWORD_REAL@db.hwpctosycjmypltjhgye.supabase.co:5432/postgres"

# -----------------------------------------------------------------
# 1. UTILIDADES Y CONEXIÓN
# -----------------------------------------------------------------

def get_db():
    """Establece conexión con el servidor PostgreSQL en la nube"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"Error crítico de conexión: {e}")
        return None

@app.template_filter('moneda')
def moneda_filter(value):
    """Formato profesional para moneda local (ej: 1.500.000)"""
    try:
        if value is None or value == "": return "0"
        return "{:,.0f}".format(float(value)).replace(",", ".")
    except: return "0"

def registrar_log(accion, detalles=""):
    """Sistema de Auditoría para el Dueño (Admin)"""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                user = session.get('username', 'Sistema')
                fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cur.execute(
                    "INSERT INTO auditoria (fecha, usuario, accion, detalles) VALUES (%s,%s,%s,%s)",
                    (fecha, user, accion, detalles)
                )
            conn.commit()
    except: pass

# -----------------------------------------------------------------
# 2. LÓGICA DE CONTROL DE CAJA DISPONIBLE
# -----------------------------------------------------------------

def calcular_disponible():
    """Calcula el efectivo real disponible para prestar"""
    with get_db() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute("SELECT value FROM settings WHERE key='cap_inicial'")
            c_i = float(cur.fetchone()['value'])
            
            cur.execute("SELECT SUM(amount) as s FROM reinvestments")
            r = cur.fetchone()['s'] or 0.0
            
            cur.execute("SELECT SUM(capital) as s FROM loans")
            p_p = cur.fetchone()['s'] or 0.0
            
            cur.execute("SELECT SUM(amount) as s FROM payments")
            p_t = cur.fetchone()['s'] or 0.0
            
            return (c_i + r - p_p + p_t)

# -----------------------------------------------------------------
# 3. INICIALIZACIÓN DE TABLAS (POSTGRESQL)
# -----------------------------------------------------------------

def init_db():
    """Crea la estructura de datos si no existe en la nube"""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS clientes (
                id SERIAL PRIMARY KEY, nombre TEXT, tel TEXT, 
                cedula TEXT UNIQUE, dir TEXT, fecha_registro TEXT)""")
            
            cur.execute("""CREATE TABLE IF NOT EXISTS loans (
                id SERIAL PRIMARY KEY, cliente_id INTEGER, 
                capital FLOAT8, total_due FLOAT8, cuotas INTEGER, 
                frecuencia TEXT, date TEXT, estado TEXT DEFAULT 'ACTIVO')""")
            
            cur.execute("""CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY, loan_id INTEGER, 
                amount FLOAT8, date TEXT, nota TEXT)""")
            
            cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            cur.execute("CREATE TABLE IF NOT EXISTS reinvestments (id SERIAL PRIMARY KEY, amount FLOAT8, date TEXT, nota TEXT)")
            cur.execute("CREATE TABLE IF NOT EXISTS usuarios (id SERIAL PRIMARY KEY, role TEXT, username TEXT UNIQUE, pin TEXT)")
            cur.execute("CREATE TABLE IF NOT EXISTS auditoria (id SERIAL PRIMARY KEY, fecha TEXT, usuario TEXT, accion TEXT, detalles TEXT)")
            
            # Datos base
            cur.execute("INSERT INTO settings (key, value) VALUES ('cap_inicial', '10000000') ON CONFLICT DO NOTHING")
            cur.execute("INSERT INTO usuarios (role, username, pin) VALUES ('admin', 'admin', '1234') ON CONFLICT DO NOTHING")
        conn.commit()

# -----------------------------------------------------------------
# 4. RUTAS DE ACCESO Y DASHBOARD
# -----------------------------------------------------------------

@app.route('/')
def index():
    if not session.get('role'): return render_template('login.html')
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['POST'])
def login():
    u, p = request.form.get('user'), request.form.get('pin')
    with get_db() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM usuarios WHERE username=%s AND pin=%s", (u, p))
            user = cur.fetchone()
            if user:
                session['role'], session['username'] = user['role'], user['username']
                registrar_log("Login Success", f"Usuario {u} entró")
                return redirect(url_for('dashboard'))
    flash("Acceso denegado: PIN o Usuario incorrecto", "danger")
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if not session.get('role'): return redirect(url_for('index'))
    with get_db() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute("SELECT value FROM settings WHERE key='cap_inicial'")
            c_i = float(cur.fetchone()['value'])
            cur.execute("SELECT SUM(amount) as s FROM reinvestments")
            r = cur.fetchone()['s'] or 0.0
            cur.execute("SELECT SUM(capital) as s FROM loans")
            p_p = cur.fetchone()['s'] or 0.0
            cur.execute("SELECT SUM(total_due) as s FROM loans")
            t_d = cur.fetchone()['s'] or 0.0
            cur.execute("SELECT SUM(amount) as s FROM payments")
            p_t = cur.fetchone()['s'] or 0.0
            
            stats = {
                'disponible': (c_i + r - p_p + p_t),
                'en_calle': (t_d - p_t),
                'utilidad': (t_d - p_p)
            }
            cur.execute("""SELECT p.amount, p.date, c.nombre FROM payments p 
                           JOIN loans l ON p.loan_id = l.id JOIN clientes c ON l.cliente_id = c.id 
                           ORDER BY p.id DESC LIMIT 5""")
            movs = cur.fetchall()
    return render_template('dashboard.html', **stats, recientes=movs)

# -----------------------------------------------------------------
# 5. GESTIÓN DE PRÉSTAMOS (CONTROL DE CAJA DISPONIBLE)
# -----------------------------------------------------------------

@app.route('/prestamos', methods=['GET', 'POST'])
def prestamos():
    if not session.get('role'): return redirect(url_for('index'))
    
    if request.method == 'POST':
        cap_solicitado = float(request.form['cap'])
        caja_actual = calcular_disponible()
        
        if cap_solicitado > caja_actual:
            flash(f"ERROR: No hay fondos suficientes. Disponible: ₲ {caja_actual:,.0f}", "danger")
            registrar_log("Bloqueo Préstamo", f"Solicitó {cap_solicitado} pero solo hay {caja_actual}")
        else:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO loans (cliente_id, capital, total_due, cuotas, frecuencia, date) VALUES (%s,%s,%s,%s,%s,%s)",
                                 (request.form['cliente_id'], cap_solicitado, request.form['tot'], request.form['cuo'], 
                                  request.form['frecuencia'], datetime.now().strftime("%Y-%m-%d")))
                conn.commit()
            flash("Préstamo otorgado con éxito", "success")
            registrar_log("Nuevo Préstamo", f"Capital: {cap_solicitado}")

    with get_db() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute("""SELECT l.*, c.nombre, 
                           (l.total_due - (SELECT COALESCE(SUM(amount),0) FROM payments WHERE loan_id = l.id)) AS saldo 
                           FROM loans l JOIN clientes c ON l.cliente_id = c.id ORDER BY l.id DESC""")
            loans = cur.fetchall()
            cur.execute("SELECT id, nombre FROM clientes ORDER BY nombre ASC")
            clis = cur.fetchall()
    return render_template('prestamos.html', loans=loans, clientes=clis)

# -----------------------------------------------------------------
# 6. GESTIÓN DE COBROS Y ELIMINACIÓN (SOLUCIÓN 404)
# -----------------------------------------------------------------

@app.route('/cobrar', methods=['GET', 'POST'])
def cobrar():
    if not session.get('role'): return redirect(url_for('index'))
    if request.method == 'POST':
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO payments (loan_id, amount, date) VALUES (%s,%s,%s)",
                             (request.form['loan_id'], request.form['monto'], datetime.now().strftime("%Y-%m-%d %H:%M")))
            conn.commit()
        flash("Cobro registrado satisfactoriamente", "success")
        return redirect(url_for('historial'))
    
    with get_db() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute("""SELECT l.id, c.nombre, 
                           (l.total_due - (SELECT COALESCE(SUM(amount),0) FROM payments WHERE loan_id = l.id)) AS pendiente 
                           FROM loans l JOIN clientes c ON l.cliente_id = c.id""")
            activos = [r for r in cur.fetchall() if r['pendiente'] > 0]
    return render_template('cobrar.html', prestamos=activos)

@app.route('/eliminar_pago/<int:id>')
def eliminar_pago(id):
    """Ruta crítica para corregir errores de dedo en cobros"""
    if session.get('role') != 'admin':
        flash("Solo el administrador puede borrar cobros", "danger")
        return redirect(url_for('historial'))
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM payments WHERE id = %s", (id,))
        conn.commit()
    flash("Registro de cobro eliminado", "warning")
    registrar_log("Eliminación Cobro", f"ID Pago: {id}")
    return redirect(url_for('historial'))

# -----------------------------------------------------------------
# 7. CAPITAL, CONFIGURACIÓN Y CIERRE
# -----------------------------------------------------------------

@app.route('/capital', methods=['GET', 'POST'])
def capital():
    if not session.get('role'): return redirect(url_for('index'))
    with get_db() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            if request.method == 'POST':
                cur.execute("INSERT INTO reinvestments (amount, date, nota) VALUES (%s,%s,%s)",
                             (request.form['monto_reinv'], datetime.now().strftime("%Y-%m-%d"), request.form['nota']))
                conn.commit()
            
            cur.execute("SELECT value FROM settings WHERE key='cap_inicial'")
            cap_ini = float(cur.fetchone()['value'])
            cur.execute("SELECT SUM(amount) as s FROM reinvestments")
            total_r = cur.fetchone()['s'] or 0.0
            cur.execute("SELECT * FROM reinvestments ORDER BY id DESC")
            lista = cur.fetchall()
    return render_template('reinversion.html', cap_ini=cap_ini, total_reinv=total_r, reinversiones=lista)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    # Configuración dinámica para la nube (Render)
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)