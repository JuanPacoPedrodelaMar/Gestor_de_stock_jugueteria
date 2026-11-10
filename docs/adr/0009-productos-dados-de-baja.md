# ADR 0009 — Un producto dado de baja sigue aceptando movimientos (decisión de negocio)

**Estado:** aceptada · **Fecha:** 2026-11-08

## Contexto
La baja lógica oculta el producto del catálogo pero conserva su historial. `productos` recibe solo un `delta` numérico: no distingue una venta de una devolución o un estropeo.

## Decisión
Se **mantiene** que un producto dado de baja pueda recibir ajustes de stock. Razones: una **devolución** de un producto ya discontinuado o dar de baja stock **estropeado** son operaciones legítimas, y rechazarlas dejaría el stock desfasado de la realidad. El panel no ofrece productos inactivos en el selector, así que por la interfaz no se pueden **vender** por accidente.

## Alternativa evaluada
Validar la categoría en `movimientos` consultando antes el estado del producto: agrega una llamada HTTP por venta (latencia) y complica la saga.

## Consecuencias
Por API directa un admin/vendedor podría registrar una **venta** sobre un inactivo. Si el negocio quiere prohibirlo, el cambio es acotado (rechazar `venta`/`ingreso` sobre inactivos y agregar reactivación). Queda registrado como decisión abierta.
