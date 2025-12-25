# -*- coding: utf-8 -*-
"""
Test de login Flask - Simula el proceso completo
"""
import os
import sys

# Asegurar que el proyecto esté en el path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['DEBUG_AUTH'] = '1'

from werkzeug.security import check_password_hash

# Importar después de configurar el ambiente
from main import USERS, USERS_FILE

def test_flask_login():
    print(f"[1] USERS_FILE: {USERS_FILE}")
    print(f"[2] Usuarios en USERS global: {list(USERS.keys())}")
    print()
    
    # Simular login de admin
    user = 'admin'
    password = '1234'
    
    user_rec = USERS.get(user)
    print(f"[3] Buscando '{user}': {user_rec is not None}")
    
    if user_rec:
        stored_pwd = user_rec.get('password', '')
        print(f"[4] Hash almacenado (50 chars): {stored_pwd[:50]}...")
        print(f"[5] Es hash válido: {stored_pwd.startswith('scrypt:') or stored_pwd.startswith('pbkdf2:')}")
        
        # Este es EXACTAMENTE el código del login
        result = check_password_hash(user_rec["password"], password)
        print(f"[6] check_password_hash resultado: {result}")
        
        if result:
            print("\n✓ LOGIN DEBERÍA FUNCIONAR")
        else:
            print("\n✗ LOGIN FALLARÍA - Investigar por qué")
    else:
        print("[ERROR] Usuario no encontrado en USERS")

if __name__ == '__main__':
    print("=" * 60)
    print("TEST DE LOGIN FLASK")
    print("=" * 60)
    print()
    test_flask_login()
