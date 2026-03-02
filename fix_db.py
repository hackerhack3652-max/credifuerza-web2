import sqlite3

def fix():
    conn = sqlite3.connect("credifuerza_web.sqlite3")
    try:
        conn.execute("ALTER TABLE reinvestments ADD COLUMN nota TEXT")
        conn.commit()
        print("Columna 'nota' añadida con éxito.")
    except sqlite3.OperationalError:
        print("La columna ya existía o hubo un error.")
    finally:
        conn.close()

if __name__ == "__main__":
    fix()