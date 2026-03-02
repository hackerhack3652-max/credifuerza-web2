# =================================================================
# CREDIFUERZA ENTERPRISE CLOUD v14.0 - SISTEMA PROFESIONAL
# =================================================================
# Licencia: Comercial / Venta SaaS
# Infraestructura: Flask + PostgreSQL (Supabase) + Render
# =================================================================

import os
import psycopg2
import logging
from psycopg2 import extras
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify

# Configuración de Logging para auditoría técnica
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', '7f8a9b2c3d4e5f6g7h8i9j0k1l2m3n4o5p')

# --- CONFIGURACIÓN DE CONEXIÓN ---
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db():
    """Gestiona la conexión al pool de PostgreSQL en Supabase"""
    try:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
        return conn
    except Exception as e:
        logger.error(f"Error crítico de conexión a DB: {e}")
        return None

# --- HERRAMIENTAS DE FORMATO Y LÓGICA FINANCIERA ---
@app.template_filter('moneda')
def moneda_filter(value):
    """Formateo de miles para divisas (ej: 1.000.000)"""
    try:
        if value is None: return "0"
        return "{:,.0f}".format(float(value)).replace(",", ".")
    except (ValueError, TypeError):
        return "0"

def registrar_auditoria(usuario, accion, tabla, registro_id, detalles=""):
    """Sistema de log para prevenir fraudes internos"""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cur.execute("""
                    INSERT INTO auditoria (fecha, usuario, accion, tabla, registro_id, detalles)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (fecha, usuario, accion, tabla, registro_id, detalles))
            conn.commit()
    except Exception as e:
        logger.error(f"Error en log de auditoría: {e}")

# --- INICIALIZACIÓN DE LA ESTRUCTURA CLOUD ---
def init_db():
    """Crea el esquema completo si es una base de datos nueva"""
    tables = [
        """CREATE TABLE IF NOT EXISTS clientes (
            id SERIAL PRIMARY KEY, 
            nombre VARCHAR(100) NOT NULL, 
            cedula VARCHAR(20) UNIQUE NOT NULL,
            telefono VARCHAR(20), 
            direccion TEXT, 
            referencia TEXT,
            fecha_registro DATE DEFAULT CURRENT_DATE)""",
        
        """CREATE TABLE IF NOT EXISTS loans (
            id SERIAL PRIMARY KEY, 
            cliente_id INTEGER REFERENCES clientes(id),
            capital FLOAT8 NOT NULL, 
            interes_total FLOAT8 NOT NULL,
            total_deuda FLOAT8 NOT NULL, 
            cuotas_total INTEGER NOT NULL,
            cuotas_pagadas INTEGER DEFAULT 0,
            frecuencia VARCHAR(20), 
            monto_cuota FLOAT8,
            fecha_inicio DATE, 
            fecha_vencimiento DATE,
            estado VARCHAR(20) DEFAULT 'ACTIVO',
            notas TEXT)""",
        
        """CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY, 
            loan_id INTEGER REFERENCES loans(id),
            monto FLOAT8 NOT NULL, 
            fecha_pago TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            metodo_pago VARCHAR(30) DEFAULT 'EFECTIVO',
            recibido_por VARCHAR(50),
            nota TEXT)""",
            
        """CREATE TABLE IF NOT EXISTS settings (
            key VARCHAR(50) PRIMARY KEY, 
            value TEXT)""",
            
        """CREATE TABLE IF NOT EXISTS reinvestments (
            id SERIAL PRIMARY KEY, 
            monto FLOAT8 NOT NULL, 
            fecha DATE DEFAULT CURRENT_DATE, 
            descripcion TEXT)""",
            
        """CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY, 
            username VARCHAR(50) UNIQUE, 
            pin VARCHAR(10), 
            role VARCHAR(20) DEFAULT 'cobrador',
            nombre_real VARCHAR(100))""",
            
        """CREATE TABLE IF NOT EXISTS auditoria (
            id SERIAL PRIMARY KEY, 
            fecha TIMESTAMP, 
            usuario VARCHAR(50), 
            accion VARCHAR(50), 
            tabla VARCHAR(50),
            registro_id INTEGER,
            detalles TEXT)"""
    ]
    
    conn = get_db()
    if conn:
        with conn:
            with conn.cursor() as cur:
                for table_sql in tables:
                    cur.execute(table_sql)
                # Datos iniciales obligatorios
                cur.execute("INSERT INTO settings (key, value) VALUES ('cap_inicial', '5000000') ON CONFLICT DO NOTHING")
                cur.execute("INSERT INTO usuarios (username, pin, role, nombre_real) VALUES ('admin', '1234', 'admin', 'Administrador Principal') ON CONFLICT DO NOTHING")
        conn.close()

# --- LÓGICA DE NEGOCIO (CAJA Y FLUJO) ---
def obtener_resumen_caja():
    """Calcula la salud financiera del negocio en tiempo real"""
    with get_db() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute("SELECT CAST(value AS FLOAT8) FROM settings WHERE key='cap_inicial'")
            base = cur.fetchone()['value']
            
            cur.execute("SELECT SUM(monto) as s FROM reinvestments")
            reinv = cur.fetchone()['s'] or 0.0
            
            cur.execute("SELECT SUM(capital) as s FROM loans")
            prestado = cur.fetchone()['s'] or 0.0
            
            cur.execute("SELECT SUM(total_deuda) as s FROM loans WHERE estado='ACTIVO'")
            en_calle_total = cur.fetchone()['s'] or 0.0
            
            cur.execute("SELECT SUM(monto) as s FROM payments")
            cobrado = cur.fetchone()['s'] or 0.0
            
            disponible = (base + reinv - prestado + cobrado)
            utilidad_esperada = (en_calle_total - (prestado * (en_calle_total/prestado if prestado > 0 else 1)))
            
            return {
                "disponible": disponible,
                "en_calle": en_calle_total - cobrado,
                "cobrado_total": cobrado,
                "capital_base": base + reinv
            }

# --- CONTROLADORES DE RUTA (VISTAS) ---

@app.route('/')
def root():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def auth():
    user = request.form.get('user')
    pin = request.form.get('pin')
    
    with get_db() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM usuarios WHERE username=%s AND pin=%s", (user, pin))
            account = cur.fetchone()
            
            if account:
                session.permanent = True
                session['user_id'] = account['id']
                session['username'] = account['username']
                session['role'] = account['role']
                registrar_auditoria(user, "LOGIN", "usuarios", account['id'], "Ingreso exitoso")
                return redirect(url_for('dashboard'))
    
    flash("Credenciales incorrectas. Verifique su PIN.", "danger")
    return redirect(url_for('root'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('root'))
    
    resumen = obtener_resumen_caja()
    with get_db() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            # Clientes con cuotas vencidas (Simulado por fecha)
            cur.execute("""
                SELECT l.id, c.nombre, l.monto_cuota, l.fecha_vencimiento 
                FROM loans l JOIN clientes c ON l.cliente_id = c.id 
                WHERE l.estado = 'ACTIVO' AND l.fecha_vencimiento < CURRENT_DATE
                LIMIT 5
            """)
            vencidos = cur.fetchall()
            
            cur.execute("SELECT COUNT(*) as total FROM clientes")
            total_clientes = cur.fetchone()['total']
            
    return render_template('dashboard.html', data=resumen, alertas=vencidos, n_cli=total_clientes)

@app.route('/clientes', methods=['GET', 'POST'])
def gestionar_clientes():
    if 'user_id' not in session: return redirect(url_for('root'))
    
    if request.method == 'POST':
        nombre = request.form.get('nombre').upper()
        cedula = request.form.get('cedula')
        tel = request.form.get('telefono')
        dir = request.form.get('direccion')
        
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO clientes (nombre, cedula, telefono, direccion) 
                        VALUES (%s, %s, %s, %s) RETURNING id
                    """, (nombre, cedula, tel, dir))
                    nuevo_id = cur.fetchone()[0]
                conn.commit()
                registrar_auditoria(session['username'], "CREATE", "clientes", nuevo_id)
                flash(f"Cliente {nombre} registrado.", "success")
        except psycopg2.IntegrityError:
            flash("Error: Esa cédula ya existe en el sistema.", "warning")
            
    with get_db() as conn:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM clientes ORDER BY nombre ASC")
            lista = cur.fetchall()
            
    return render_template('clientes.html', clientes=lista)

@app.route('/nuevo-prestamo', methods=['POST'])
def crear_prestamo():
    if session.get('role') != 'admin':
        flash("No tiene permisos para otorgar créditos.", "danger")
        return redirect(url_for('dashboard'))
        
    c_id = request.form.get('cliente_id')
    cap = float(request.form.get('capital'))
    interes_porcentaje = float(request.form.get('interes')) # Ej: 20
    cuotas = int(request.form.get('cuotas'))
    frecuencia = request.form.get('frecuencia') # Diario, Semanal, Mensual
    
    # Cálculo Financiero
    total_interes = cap * (interes_porcentaje / 100)
    total_deuda = cap + total_interes
    monto_cuota = total_deuda / cuotas
    
    # Validar Caja
    caja = obtener_resumen_caja()
    if cap > caja['disponible']:
        flash("OPERACIÓN CANCELADA: Fondos insuficientes en caja.", "danger")
        return redirect(url_for('dashboard'))
        
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO loans (cliente_id, capital, interes_total, total_deuda, cuotas_total, frecuencia, monto_cuota, fecha_inicio, estado)
                VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_DATE, 'ACTIVO') RETURNING id
            """, (c_id, cap, total_interes, total_deuda, cuotas, frecuencia, monto_cuota))
            l_id = cur.fetchone()[0]
        conn.commit()
        registrar_auditoria(session['username'], "OTORGAR_PRESTAMO", "loans", l_id, f"Monto: {cap}")
        
    flash("Préstamo aprobado y desembolsado correctamente.", "success")
    return redirect(url_for('prestamos_lista'))

@app.route('/registrar-pago', methods=['POST'])
def registrar_pago():
    l_id = request.form.get('loan_id')
    monto = float(request.form.get('monto'))
    nota = request.form.get('nota', '')
    
    with get_db() as conn:
        with conn.cursor() as cur:
            # Insertar Pago
            cur.execute("""
                INSERT INTO payments (loan_id, monto, recibido_por, nota) 
                VALUES (%s, %s, %s, %s)
            """, (l_id, monto, session['username'], nota))
            
            # Actualizar Estado del Préstamo
            cur.execute("SELECT total_deuda FROM loans WHERE id=%s", (l_id,))
            total_due = cur.fetchone()[0]
            
            cur.execute("SELECT SUM(monto) FROM payments WHERE loan_id=%s", (l_id,))
            total_pagado = cur.fetchone()[0]
            
            if total_pagado >= total_due:
                cur.execute("UPDATE loans SET estado='FINALIZADO' WHERE id=%s", (l_id,))
                
        conn.commit()
        flash(f"Cobro de {monto} registrado exitosamente.", "success")
        
    return redirect(url_for('dashboard'))

@app.route('/configuracion', methods=['GET', 'POST'])
def config():
    if session.get('role') != 'admin': return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        nuevo_cap = request.form.get('cap_inicial')
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE settings SET value=%s WHERE key='cap_inicial'", (nuevo_cap,))
            conn.commit()
        flash("Configuración de capital base actualizada.", "info")
        
    return render_template('config.html')

@app.route('/logout')
def logout():
    registrar_auditoria(session.get('username'), "LOGOUT", "usuarios", 0)
    session.clear()
    return redirect(url_for('root'))

# --- CIERRE Y ARRANQUE ---
if __name__ == '__main__':
    init_db()
    # Soporte para puerto dinámico de Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
