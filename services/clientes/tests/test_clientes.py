"""
Clientes: permisos por rol, alta (ID propio, documento repetible, email y
teléfono opcionales), búsqueda y consulta.

Se usa `client.como(rol, sub, dni)` para cambiar de usuario a mitad de cada caso.
"""
import pytest

CLIENTES = "/api/v1/clientes"


def _cliente(client, rol="ventas", sub="5", **datos):
    cuerpo = {"documento": "30123456", **datos}
    resp = client.como(rol, sub).post(CLIENTES, json=cuerpo)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Autenticación y roles
# ---------------------------------------------------------------------------

def test_sin_token_devuelve_401(client_sin_auth):
    assert client_sin_auth.get(CLIENTES).status_code == 401
    assert client_sin_auth.post(CLIENTES, json={"documento": "1234567"}).status_code == 401


def test_con_un_token_invalido_devuelve_401(client_sin_auth):
    resp = client_sin_auth.get(CLIENTES, headers={"Authorization": "Bearer no-es-un-jwt"})

    assert resp.status_code == 401


@pytest.mark.parametrize("rol", ["admin", "ventas", "mixto"])
def test_crean_clientes_admin_ventas_y_mixto(client, rol):
    assert client.como(rol, "5").post(CLIENTES, json={"documento": "30123456"}).status_code == 201


def test_almacen_no_accede_a_clientes(client):
    cliente = _cliente(client)
    almacen = client.como("almacen", "5")

    assert almacen.post(CLIENTES, json={"documento": "1234567"}).status_code == 403
    assert almacen.get(CLIENTES).status_code == 403
    assert almacen.get(f"{CLIENTES}/{cliente['id_cliente']}").status_code == 403


def test_un_rol_inexistente_no_accede(client):
    """El rol genérico "empleado" de versiones anteriores ya no existe."""
    assert client.como("empleado", "5").get(CLIENTES).status_code == 403


# ---------------------------------------------------------------------------
# Alta
# ---------------------------------------------------------------------------

def test_el_id_lo_asigna_el_sistema_y_email_y_telefono_son_opcionales(client):
    solo_documento = _cliente(client)
    completo = _cliente(client, email="ana@ejemplo.com", telefono="+54 376 4123456")

    assert solo_documento["id_cliente"] != completo["id_cliente"]
    assert solo_documento["email"] is None and solo_documento["telefono"] is None
    assert completo["email"] == "ana@ejemplo.com" and completo["telefono"] == "+54 376 4123456"


def test_el_documento_puede_repetirse_entre_clientes(client):
    a = _cliente(client, documento="30123456", email="a@ejemplo.com")
    b = _cliente(client, documento="30123456", email="b@ejemplo.com")

    assert a["id_cliente"] != b["id_cliente"]
    assert a["documento"] == b["documento"]


@pytest.mark.parametrize("documento", ["X1234567", "AB-123.456/7", "1", "123456789012", "A 1234 B", "11.222.333"])
def test_acepta_documentos_de_otros_paises(client, documento):
    assert _cliente(client, documento=documento)["documento"] == documento


@pytest.mark.parametrize("telefono", ["+54 376 4123456", "(0376) 412-3456", "3764123456", "+1 (415) 555-0100"])
def test_acepta_telefonos_en_formatos_habituales(client, telefono):
    assert _cliente(client, telefono=telefono)["telefono"] == telefono


def test_email_y_telefono_vacios_cuentan_como_no_enviados(client):
    cliente = _cliente(client, email="", telefono="   ")

    assert cliente["email"] is None and cliente["telefono"] is None


@pytest.mark.parametrize(
    "cuerpo",
    [
        {},
        {"documento": ""},
        {"documento": "   "},
        {"documento": "x" * 31},
        {"documento": "30123456", "email": "no-es-un-email"},
        {"documento": "30123456", "email": "a" * 120 + "@x.com"},
        {"documento": "30123456", "telefono": "12"},
        {"documento": "30123456", "telefono": "1" * 40},
    ],
)
def test_datos_de_cliente_invalidos_devuelven_400(client, cuerpo):
    assert client.como("ventas", "5").post(CLIENTES, json=cuerpo).status_code == 400


def test_el_dni_del_empleado_que_dio_de_alta_al_cliente_sale_del_token(client, SessionLocal):
    from app.models.cliente import Cliente

    cliente = client.como("ventas", "5", dni="31222333").post(CLIENTES, json={"documento": "1234567"}).json()

    db = SessionLocal()
    try:
        assert db.get(Cliente, cliente["id_cliente"]).creado_por_dni == "31222333"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Búsqueda
# ---------------------------------------------------------------------------

@pytest.fixture()
def tres_clientes(client):
    ana = _cliente(client, documento="30123456", email="ana@ejemplo.com", telefono="+54 376 4123456")
    luis = _cliente(client, documento="X7654321", email="luis@correo.com.ar", telefono="(0376) 455-0000")
    otra_ana = _cliente(client, documento="30123456", email=None, telefono=None)
    return ana, luis, otra_ana


def _buscar(client, q=None, rol="ventas"):
    resp = client.como(rol, "5").get(CLIENTES, params={"q": q} if q is not None else None)
    assert resp.status_code == 200, resp.text
    return [c["id_cliente"] for c in resp.json()]


def test_sin_texto_devuelve_los_ultimos_primero(client, tres_clientes):
    ana, luis, otra_ana = tres_clientes

    assert _buscar(client) == [otra_ana["id_cliente"], luis["id_cliente"], ana["id_cliente"]]


def test_busca_por_documento_y_trae_a_todos_los_repetidos(client, tres_clientes):
    ana, luis, otra_ana = tres_clientes

    assert sorted(_buscar(client, "30123456")) == sorted([ana["id_cliente"], otra_ana["id_cliente"]])


def test_busca_por_parte_del_documento_sin_distinguir_mayusculas(client, tres_clientes):
    ana, luis, _ = tres_clientes

    assert _buscar(client, "x765") == [luis["id_cliente"]]


def test_busca_por_email(client, tres_clientes):
    ana, luis, _ = tres_clientes

    assert _buscar(client, "luis@correo") == [luis["id_cliente"]]
    assert _buscar(client, "EJEMPLO.com") == [ana["id_cliente"]]


def test_busca_por_telefono(client, tres_clientes):
    ana, luis, _ = tres_clientes

    assert _buscar(client, "455-0000") == [luis["id_cliente"]]


@pytest.mark.parametrize("formato", ["{}", "#{}"])
def test_busca_por_id_exacto_con_o_sin_numeral(client, tres_clientes, formato):
    ana, luis, _ = tres_clientes

    assert luis["id_cliente"] in _buscar(client, formato.format(luis["id_cliente"]))


def test_el_id_es_coincidencia_exacta_no_parcial(client, tres_clientes):
    """Buscar "1" no trae al cliente 10 o 11 por su id (sí a quien tenga un 1 en el documento)."""
    for i in range(12):
        _cliente(client, documento=f"AA{i}")
    ids = _buscar(client, "#1")

    assert 1 in ids and 10 not in ids and 11 not in ids


def test_los_comodines_de_like_se_buscan_literalmente(client, tres_clientes):
    assert _buscar(client, "%") == []
    assert _buscar(client, "_") == []


def test_una_busqueda_sin_resultados_devuelve_lista_vacia(client, tres_clientes):
    assert _buscar(client, "no-existe") == []


def test_el_limite_de_resultados_se_respeta(client):
    for i in range(5):
        _cliente(client, documento=f"D{i}")

    resp = client.como("ventas", "5").get(CLIENTES, params={"limite": 3})

    assert len(resp.json()) == 3
    assert client.get(CLIENTES, params={"limite": 0}).status_code == 400


@pytest.mark.parametrize("peligroso", ["' OR '1'='1", "1; DROP TABLE clientes;--", "<script>", "../../etc/passwd"])
def test_buscar_con_texto_peligroso_no_rompe_ni_filtra_de_mas(client, tres_clientes, peligroso):
    assert _buscar(client, peligroso) == []
    assert len(_buscar(client)) == 3  # la tabla sigue intacta


# ---------------------------------------------------------------------------
# Consulta de uno (también la usa Movimientos para validar un id_cliente)
# ---------------------------------------------------------------------------

def test_obtener_un_cliente_y_el_404(client):
    cliente = _cliente(client, email="ana@ejemplo.com")

    ok = client.get(f"{CLIENTES}/{cliente['id_cliente']}")
    falta = client.get(f"{CLIENTES}/9999")

    assert ok.status_code == 200 and ok.json()["email"] == "ana@ejemplo.com"
    assert falta.status_code == 404
    assert "9999" in falta.json()["mensaje"]


def test_el_historial_de_movimientos_ya_no_vive_en_este_servicio(client):
    """Lo tiene Movimientos (GET /api/v1/movimientos?id_cliente=N), que es dueño de esos datos."""
    cliente = _cliente(client)

    assert client.get(f"{CLIENTES}/{cliente['id_cliente']}/movimientos").status_code == 404
