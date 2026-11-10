"""
Auditoría de contraste WCAG 2.x AA (4.5:1 texto normal, 3:1 texto grande) de los pares
texto/fondo declarados en el CSS de frontend/index.html. Sale con código 1 si alguno no cumple (CI).
Uso: python scripts/auditar_contraste.py [ruta/a/index.html] [--todo]
"""
import re, sys, itertools

def hex_rgb(h):
    h = h.lstrip('#')
    if len(h) == 3: h = ''.join(c*2 for c in h)
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def lum(rgb):
    def f(c):
        c /= 255
        return c/12.92 if c <= 0.03928 else ((c+0.055)/1.055) ** 2.4
    r, g, b = map(f, rgb)
    return 0.2126*r + 0.7152*g + 0.0722*b

def ratio(a, b):
    la, lb = lum(hex_rgb(a)), lum(hex_rgb(b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)

def auditar(ruta):
    html = open(ruta, encoding='utf-8').read()
    css = re.search(r'<style>(.*?)</style>', html, re.S).group(1)
    variables = dict(re.findall(r'--([\w-]+)\s*:\s*(#[0-9A-Fa-f]{3,6})', css))
    def resolver(v):
        v = v.strip()
        m = re.match(r'var\(--([\w-]+)\)', v)
        if m: return variables.get(m.group(1))
        m = re.match(r'(#[0-9A-Fa-f]{3,6})\b', v)
        return m.group(1) if m else None
    fondos_base = [variables['crema'], '#FFFFFF']
    resultados = []
    for sel, cuerpo in re.findall(r'([^{}@]+)\{([^{}]*)\}', css):
        sel = ' '.join(sel.split())
        col = re.search(r'(?<![-\w])color\s*:\s*([^;]+)', cuerpo)
        bg = re.search(r'background(?:-color)?\s*:\s*([^;]+)', cuerpo)
        if not col: continue
        fg = resolver(col.group(1))
        if not fg: continue
        tam = re.search(r'font-size\s*:\s*(\d+)px', cuerpo)
        peso = re.search(r'font-weight\s*:\s*(\d+)', cuerpo)
        fondo = resolver(bg.group(1)) if bg else None
        fondos = [fondo] if fondo else fondos_base
        for f in fondos:
            resultados.append((sel, fg, f, ratio(fg, f), int(tam.group(1)) if tam else None, int(peso.group(1)) if peso else None))
    return resultados

# Selectores cuyo fondo real es el del botón padre (que el análisis no resuelve): se verifican a mano.
# Los botones de rol llevan texto blanco sobre #CC3900 / #E70047 / #198084 / #AC481A: todos >= 4.6:1.
FALSOS_POSITIVOS = ("small",)


if __name__ == '__main__':
    ruta = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "frontend/index.html"
    malos = 0
    for sel, fg, bg, r, tam, peso in auditar(ruta):
        if sel.endswith(FALSOS_POSITIVOS) and ".btn-rol" in sel:
            continue
        grande = tam is not None and (tam >= 24 or (tam >= 19 and (peso or 400) >= 700))
        minimo = 3.0 if grande else 4.5
        estado = 'OK ' if r >= minimo else 'FALLA'
        if r < minimo: malos += 1
        if '--todo' in sys.argv or r < minimo:
            print(f'{estado} {r:5.2f}:1 (mín {minimo}) fg={fg} bg={bg} tam={tam} :: {sel[:70]}')
    print('Pares que no cumplen WCAG AA:', malos)
    sys.exit(1 if malos else 0)
