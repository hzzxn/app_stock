# -*- coding: utf-8 -*-
"""
Test de autenticación - Verifica que check_password_hash funcione correctamente
"""
import os
import sys
import json

# Asegurar que el proyecto esté en el path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import check_password_hash, generate_password_hash

def test_auth():
    """Prueba la autenticación directamente"""
    users_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'users.json')
    
    print(f"[1] Ruta users.json: {os.path.abspath(users_file)}")
    print(f"[2] Archivo existe: {os.path.exists(users_file)}")
    
    if not os.path.exists(users_file):
        print("[ERROR] users.json no existe!")
        return False
    
    with open(users_file, 'r', encoding='utf-8') as f:
        users = json.load(f)
    
    print(f"[3] Usuarios cargados: {list(users.keys())}")
    print()
    
    # Test cases
    test_cases = [
        ('admin', '1234'),
        ('china', 'changeme'),
        ('operador', '1234'),
    ]
    
    all_passed = True
    for username, password in test_cases:
        user_data = users.get(username)
        if not user_data:
            print(f"[SKIP] Usuario '{username}' no existe")
            continue
        
        stored_hash = user_data.get('password', '')
        
        # Verificar que es un hash válido
        is_valid_hash = stored_hash.startswith('scrypt:') or stored_hash.startswith('pbkdf2:')
        
        # Probar check_password_hash
        result = check_password_hash(stored_hash, password)
        
        status = "✓ OK" if result else "✗ FALLO"
        print(f"[TEST] {username}/{password}: {status}")
        print(f"       Hash válido: {is_valid_hash}")
        print(f"       Hash (50 chars): {stored_hash[:50]}...")
        print()
        
        if not result:
            all_passed = False
    
    return all_passed

if __name__ == '__main__':
    print("=" * 60)
    print("TEST DE AUTENTICACIÓN")
    print("=" * 60)
    print()
    
    success = test_auth()
    
    print("=" * 60)
    if success:
        print("RESULTADO: Todas las pruebas pasaron ✓")
    else:
        print("RESULTADO: Algunas pruebas fallaron ✗")
    print("=" * 60)
