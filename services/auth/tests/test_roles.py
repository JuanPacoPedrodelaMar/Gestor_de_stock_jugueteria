"""
Tests de control de acceso por rol (issue #7; roles admin, almacen, ventas y mixto).
"""


def _auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def test_me_requiere_autenticacion(client):
    resp = client.get("/api/v1/auth/me")

    assert resp.status_code == 401


def test_me_devuelve_los_datos_del_usuario_autenticado(client, admin_token, crear_admin):
    resp = client.get("/api/v1/auth/me", headers=_auth_header(admin_token["access_token"]))

    assert resp.status_code == 200
    assert resp.json()["email"] == crear_admin["email"]
    assert resp.json()["rol"] == "admin"


def test_admin_puede_crear_usuarios(client, admin_token):
    resp = client.post(
        "/api/v1/auth/usuarios",
        json={"email": "nuevo@test.com", "password": "password123", "nombre": "Nuevo", "rol": "ventas", "dni": "31000111"},
        headers=_auth_header(admin_token["access_token"]),
    )

    assert resp.status_code == 201
    assert resp.json()["rol"] == "ventas"
    assert resp.json()["dni"] == "31000111"


def test_empleado_no_puede_crear_usuarios(client, crear_empleado):
    login = client.post("/api/v1/auth/login", json=crear_empleado).json()

    resp = client.post(
        "/api/v1/auth/usuarios",
        json={"email": "otro@test.com", "password": "password123", "nombre": "Otro", "rol": "ventas", "dni": "31000222"},
        headers=_auth_header(login["access_token"]),
    )

    assert resp.status_code == 403


def test_empleado_no_puede_listar_usuarios(client, crear_empleado):
    login = client.post("/api/v1/auth/login", json=crear_empleado).json()

    resp = client.get("/api/v1/auth/usuarios", headers=_auth_header(login["access_token"]))

    assert resp.status_code == 403


def test_admin_puede_listar_usuarios(client, admin_token, crear_empleado):
    resp = client.get("/api/v1/auth/usuarios", headers=_auth_header(admin_token["access_token"]))

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_crear_usuario_con_email_duplicado_devuelve_409(client, admin_token, crear_admin):
    resp = client.post(
        "/api/v1/auth/usuarios",
        json={"email": crear_admin["email"], "password": "password123", "nombre": "Duplicado", "rol": "ventas", "dni": "31000333"},
        headers=_auth_header(admin_token["access_token"]),
    )

    assert resp.status_code == 409


def test_empleado_puede_ver_su_propio_perfil(client, crear_empleado):
    """/me acepta cualquier rol, a diferencia de /usuarios."""
    login = client.post("/api/v1/auth/login", json=crear_empleado).json()

    resp = client.get("/api/v1/auth/me", headers=_auth_header(login["access_token"]))

    assert resp.status_code == 200
    assert resp.json()["rol"] == "mixto"
    assert resp.json()["dni"] == "30111222"


def test_token_con_firma_invalida_es_rechazado(client):
    resp = client.get("/api/v1/auth/me", headers=_auth_header("token.invalido.falso"))

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Roles de empleado y DNI
# ---------------------------------------------------------------------------

def test_empleado_sin_dni_es_rechazado(client, admin_token):
    resp = client.post(
        "/api/v1/auth/usuarios",
        json={"email": "sindni@test.com", "password": "password123", "nombre": "Sin DNI", "rol": "almacen"},
        headers=_auth_header(admin_token["access_token"]),
    )

    assert resp.status_code == 400


def test_admin_puede_no_tener_dni(client, admin_token):
    resp = client.post(
        "/api/v1/auth/usuarios",
        json={"email": "admin2@test.com", "password": "password123", "nombre": "Otro admin", "rol": "admin"},
        headers=_auth_header(admin_token["access_token"]),
    )

    assert resp.status_code == 201
    assert resp.json()["dni"] is None


def test_dni_con_formato_invalido_es_rechazado(client, admin_token):
    for dni in ["12", "123456789", "12a45678", "1234567; --"]:
        resp = client.post(
            "/api/v1/auth/usuarios",
            json={"email": "x@test.com", "password": "password123", "nombre": "X", "rol": "ventas", "dni": dni},
            headers=_auth_header(admin_token["access_token"]),
        )
        assert resp.status_code == 400, dni


def test_crear_usuario_con_dni_duplicado_devuelve_409(client, admin_token, crear_empleado):
    resp = client.post(
        "/api/v1/auth/usuarios",
        json={"email": "otro@test.com", "password": "password123", "nombre": "Otro", "rol": "ventas", "dni": "30111222"},
        headers=_auth_header(admin_token["access_token"]),
    )

    assert resp.status_code == 409


def test_el_rol_generico_empleado_ya_no_existe(client, admin_token):
    resp = client.post(
        "/api/v1/auth/usuarios",
        json={"email": "viejo@test.com", "password": "password123", "nombre": "Viejo", "rol": "empleado", "dni": "31000444"},
        headers=_auth_header(admin_token["access_token"]),
    )

    assert resp.status_code == 400


def test_cada_rol_de_empleado_puede_ver_su_perfil(client, crear_almacen, crear_ventas, crear_empleado):
    esperados = [(crear_almacen, "almacen"), (crear_ventas, "ventas"), (crear_empleado, "mixto")]
    for credenciales, rol in esperados:
        login = client.post("/api/v1/auth/login", json=credenciales).json()
        resp = client.get("/api/v1/auth/me", headers=_auth_header(login["access_token"]))
        assert resp.status_code == 200
        assert resp.json()["rol"] == rol


def test_los_empleados_no_gestionan_usuarios(client, crear_almacen, crear_ventas):
    for credenciales in (crear_almacen, crear_ventas):
        login = client.post("/api/v1/auth/login", json=credenciales).json()
        resp = client.get("/api/v1/auth/usuarios", headers=_auth_header(login["access_token"]))
        assert resp.status_code == 403
