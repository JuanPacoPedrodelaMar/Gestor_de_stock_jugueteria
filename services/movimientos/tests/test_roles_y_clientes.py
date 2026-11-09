"""
Permisos por rol, empleado tomado del token e integración con el servicio de
Clientes (validación del id_cliente, copia del documento, historial por cliente).

Los clientes en sí (alta, búsqueda, validación de datos) son de services/clientes.
Acá Productos y Clientes se simulan (ProductosFalso y ClientesFalso, conftest.py);
`client.como(rol, sub, dni)` cambia de usuario a mitad de cada caso.
"""
import pytest

MOVIMIENTOS = "/api/v1/movimientos"
VENTA = {"categoria_movimiento": "venta", "cantidad_movida": 2, "id_producto": 1}


# ---------------------------------------------------------------------------
# Quién puede registrar y consultar movimientos
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rol", ["admin", "ventas", "mixto"])
def test_registran_movimientos_admin_ventas_y_mixto(client, rol):
    assert client.como(rol, "5").post(MOVIMIENTOS, json=VENTA).status_code == 201


def test_almacen_no_puede_registrar_movimientos(client, productos_mock):
    resp = client.como("almacen", "5").post(MOVIMIENTOS, json=VENTA)

    assert resp.status_code == 403
    productos_mock.assert_not_called()


@pytest.mark.parametrize("rol,esperado", [("admin", 200), ("ventas", 200), ("mixto", 200), ("almacen", 403)])
def test_consultar_el_historial_segun_el_rol(client, rol, esperado):
    assert client.como(rol, "5").get(MOVIMIENTOS).status_code == esperado
    assert client.como(rol, "5").get("/api/v1/productos/1/movimientos").status_code == esperado


def test_cualquier_rol_puede_contar_los_movimientos_de_un_producto(client):
    """Lo consulta Productos con el token de quien elimina (incluido un empleado de almacén)."""
    for rol in ("admin", "almacen", "ventas", "mixto"):
        assert client.como(rol, "5").get("/api/v1/productos/1/movimientos/cantidad").status_code == 200


def test_ningun_rol_puede_editar_ni_borrar_movimientos(client):
    creado = client.como("admin", "1").post(MOVIMIENTOS, json=VENTA).json()
    url = f"{MOVIMIENTOS}/{creado['id_movimiento']}"

    for rol in ("admin", "ventas", "mixto"):
        for metodo in ("put", "patch", "delete"):
            resp = getattr(client.como(rol, "5"), metodo)(url, **({"json": VENTA} if metodo != "delete" else {}))
            assert resp.status_code in (404, 405), (rol, metodo, resp.status_code)


# ---------------------------------------------------------------------------
# El empleado sale del token
# ---------------------------------------------------------------------------

def test_el_dni_del_empleado_sale_del_token(client):
    resp = client.como("ventas", "5", dni="31222333").post(MOVIMIENTOS, json=VENTA)

    assert resp.status_code == 201
    assert resp.json()["dni_empleado"] == "31222333"


def test_un_dni_de_empleado_enviado_en_el_pedido_se_ignora(client):
    """No se puede falsear a nombre de quién queda el movimiento."""
    pedido = {**VENTA, "dni_empleado": "99999999"}

    resp = client.como("ventas", "5", dni="31222333").post(MOVIMIENTOS, json=pedido)

    assert resp.status_code == 201
    assert resp.json()["dni_empleado"] == "31222333"


def test_dos_empleados_distintos_quedan_registrados_cada_uno_con_su_dni(client):
    a = client.como("ventas", "5", dni="31111111").post(MOVIMIENTOS, json=VENTA).json()
    b = client.como("mixto", "6", dni="32222222").post(MOVIMIENTOS, json=VENTA).json()

    assert (a["dni_empleado"], b["dni_empleado"]) == ("31111111", "32222222")


def test_un_admin_sin_dni_registra_el_movimiento_sin_empleado(client):
    from tests.conftest import payload_de

    resp = client.como("admin", "1").post(MOVIMIENTOS, json=VENTA)
    assert resp.status_code == 201  # el admin de prueba tiene DNI; el caso sin DNI se prueba abajo

    from app.core.jwt_auth import obtener_token_y_payload
    from app.main import app

    sin_dni = payload_de("admin", "1")
    sin_dni["dni"] = None
    app.dependency_overrides[obtener_token_y_payload] = lambda: ("token", sin_dni)

    resp = client.post(MOVIMIENTOS, json=VENTA)

    assert resp.status_code == 201
    assert resp.json()["dni_empleado"] is None


def test_el_reintento_con_la_misma_clave_por_otro_empleado_es_otro_pedido(client):
    """La Idempotency-Key solo vale para el mismo contenido, empleado incluido."""
    clave = {"Idempotency-Key": "clave-123"}
    primero = client.como("ventas", "5", dni="31111111").post(MOVIMIENTOS, json=VENTA, headers=clave)
    mismo = client.como("ventas", "5", dni="31111111").post(MOVIMIENTOS, json=VENTA, headers=clave)
    otro = client.como("ventas", "6", dni="32222222").post(MOVIMIENTOS, json=VENTA, headers=clave)

    assert primero.status_code == mismo.status_code == 201
    assert primero.json()["id_movimiento"] == mismo.json()["id_movimiento"]
    assert otro.status_code == 422


# ---------------------------------------------------------------------------
# Integración con el servicio de Clientes
# ---------------------------------------------------------------------------

def test_un_movimiento_con_cliente_guarda_su_id_y_una_copia_del_documento(client, clientes):
    id_cliente = clientes.alta(documento="X1234567", email="ana@ejemplo.com")

    resp = client.como("ventas", "5").post(MOVIMIENTOS, json={**VENTA, "id_cliente": id_cliente})

    assert resp.status_code == 201
    cuerpo = resp.json()
    assert cuerpo["id_cliente"] == id_cliente
    assert cuerpo["cliente_documento"] == "X1234567"


def test_el_token_del_usuario_se_reenvia_a_clientes(client, clientes):
    id_cliente = clientes.alta()

    client.como("ventas", "5").post(MOVIMIENTOS, json={**VENTA, "id_cliente": id_cliente})

    assert clientes.llamadas == [(id_cliente, "token-de-prueba-no-valido")]


def test_un_movimiento_sin_cliente_no_consulta_a_clientes(client, clientes):
    resp = client.como("ventas", "5").post(MOVIMIENTOS, json=VENTA)

    assert resp.status_code == 201
    assert resp.json()["id_cliente"] is None and resp.json()["cliente_documento"] is None
    assert clientes.llamadas == []


def test_un_cliente_inexistente_devuelve_404_y_no_registra_nada(client, productos_mock):
    resp = client.como("ventas", "5").post(MOVIMIENTOS, json={**VENTA, "id_cliente": 9999})

    assert resp.status_code == 404
    assert "9999" in resp.json()["mensaje"]
    productos_mock.assert_not_called()  # no se tocó el stock
    assert client.get(MOVIMIENTOS).json() == []


def test_si_clientes_no_responde_devuelve_503_y_no_registra_nada(client, clientes, productos_mock):
    id_cliente = clientes.alta()
    clientes.caido = True

    resp = client.como("ventas", "5").post(MOVIMIENTOS, json={**VENTA, "id_cliente": id_cliente})

    assert resp.status_code == 503
    productos_mock.assert_not_called()
    assert client.get(MOVIMIENTOS).json() == []


def test_sin_cliente_el_movimiento_se_registra_aunque_clientes_este_caido(client, clientes):
    """Clientes es opcional: su caída no frena las ventas que no lo usan."""
    clientes.caido = True

    assert client.como("ventas", "5").post(MOVIMIENTOS, json=VENTA).status_code == 201


def test_un_reintento_con_la_misma_clave_no_vuelve_a_consultar_a_clientes(client, clientes):
    id_cliente = clientes.alta(documento="X1234567")
    pedido = {**VENTA, "id_cliente": id_cliente}
    headers = {"Idempotency-Key": "venta-con-cliente-1"}
    vendedor = client.como("ventas", "5", dni="31222333")

    primero = vendedor.post(MOVIMIENTOS, json=pedido, headers=headers)
    clientes.caido = True  # el reintento no debería necesitarlo
    segundo = vendedor.post(MOVIMIENTOS, json=pedido, headers=headers)

    assert primero.status_code == segundo.status_code == 201
    assert primero.json()["id_movimiento"] == segundo.json()["id_movimiento"]
    assert len(clientes.llamadas) == 1


def test_la_misma_clave_con_otro_cliente_es_un_pedido_distinto(client, clientes):
    uno, otro = clientes.alta(documento="A1"), clientes.alta(documento="B2")
    headers = {"Idempotency-Key": "clave-compartida"}
    vendedor = client.como("ventas", "5")

    assert vendedor.post(MOVIMIENTOS, json={**VENTA, "id_cliente": uno}, headers=headers).status_code == 201
    assert vendedor.post(MOVIMIENTOS, json={**VENTA, "id_cliente": otro}, headers=headers).status_code == 422


def test_el_documento_guardado_no_cambia_si_despues_se_corrige_el_cliente(client, clientes):
    """La copia refleja el dato al momento de la venta."""
    id_cliente = clientes.alta(documento="VIEJO-1")
    client.como("ventas", "5").post(MOVIMIENTOS, json={**VENTA, "id_cliente": id_cliente})

    clientes.clientes[id_cliente]["documento"] = "NUEVO-2"

    assert client.get(MOVIMIENTOS).json()[0]["cliente_documento"] == "VIEJO-1"


def test_los_clientes_ya_no_se_gestionan_desde_este_servicio(client):
    assert client.get("/api/v1/clientes").status_code == 404
    assert client.post("/api/v1/clientes", json={"documento": "1234567"}).status_code == 404


# ---------------------------------------------------------------------------
# Historial por cliente: GET /api/v1/movimientos?id_cliente=N
# ---------------------------------------------------------------------------

def test_el_historial_de_un_cliente_solo_trae_sus_movimientos(client, clientes):
    ana, otra_ana = clientes.alta(documento="30123456"), clientes.alta(documento="30123456")  # mismo documento
    venta = client.como("ventas", "5")
    venta.post(MOVIMIENTOS, json={**VENTA, "id_cliente": ana, "cantidad_movida": 1})
    venta.post(MOVIMIENTOS, json={**VENTA, "id_cliente": ana, "cantidad_movida": 2})
    venta.post(MOVIMIENTOS, json={**VENTA, "id_cliente": otra_ana, "cantidad_movida": 7})
    venta.post(MOVIMIENTOS, json=VENTA)  # sin cliente

    historial = venta.get(MOVIMIENTOS, params={"id_cliente": ana}).json()

    assert [m["cantidad_movida"] for m in historial] == [2, 1]  # el más reciente primero
    assert all(m["id_cliente"] == ana for m in historial)
    assert venta.get(MOVIMIENTOS, params={"id_cliente": otra_ana}).json()[0]["cantidad_movida"] == 7
    assert len(venta.get(MOVIMIENTOS).json()) == 4  # sin filtro: todos


def test_el_historial_de_un_cliente_sin_movimientos_es_una_lista_vacia(client):
    assert client.get(MOVIMIENTOS, params={"id_cliente": 123}).json() == []


@pytest.mark.parametrize("valor", ["0", "-1", "abc", "1.5"])
def test_id_cliente_invalido_en_el_filtro_devuelve_400(client, valor):
    assert client.get(MOVIMIENTOS, params={"id_cliente": valor}).status_code == 400


@pytest.mark.parametrize("rol,esperado", [("admin", 200), ("ventas", 200), ("mixto", 200), ("almacen", 403)])
def test_el_historial_por_cliente_respeta_los_roles(client, rol, esperado):
    assert client.como(rol, "5").get(MOVIMIENTOS, params={"id_cliente": 1}).status_code == esperado


def test_los_movimientos_anteriores_conservan_su_dni_de_cliente(client, SessionLocal):
    """Los movimientos viejos (con dni_cliente suelto) se siguen mostrando."""
    from app.models.movimiento import Movimiento

    db = SessionLocal()
    try:
        db.add(Movimiento(categoria_movimiento="venta", cantidad_movida=1, id_producto=1, dni_cliente="20111222"))
        db.commit()
    finally:
        db.close()

    viejo = client.get(MOVIMIENTOS).json()[0]

    assert viejo["dni_cliente"] == "20111222"
    assert viejo["id_cliente"] is None and viejo["cliente_documento"] is None
