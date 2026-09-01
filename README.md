# Monitoreo de plataformas

Vigila que el sitio de un cliente **funcione de verdad**, no solo que responda.

## Por qué no basta un monitoreo de estante

Los servicios comunes revisan el código de respuesta HTTP. El primer sitio que
vigila este monitor devuelve **HTTP 200 mostrando “Página no encontrada”**, y una
de sus URL de curso devolvía una imagen PNG en lugar de la página. Un monitor que
solo mire el código da esas fallas por buenas.

Este revisa además el **contenido**: busca frases que significan “cargó pero está
rota”, tomadas de los reportes reales del equipo del cliente.

## Qué hace

- Revisa cada 10 minutos las páginas clave del sitio.
- Avisa **solo cuando algo cambia**: una vez al romperse, otra al restablecerse
  y con cuánto duró. Ese segundo dato es el que normalmente nadie tiene.
- Reintenta antes de dar una falla por buena, para no gritar por un tropiezo de red.
- Deja historial de cada incidente, que es de donde sale el reporte semanal.

## Cómo avisa

El monitor no manda mensajes. Escribe el detalle en un contacto del CRM y le pone
una etiqueta; esa etiqueta dispara un workflow que manda el aviso y luego se quita
la etiqueta para que la siguiente alerta pueda dispararse.

Si el CRM falla, la corrida sale con error y **GitHub manda su propio correo** —
un segundo canal que no depende de nada del proyecto.

## Estructura

```
monitor/
  clientes/<nombre>.json   configuración de cada cliente
  sitio.py                 qué se revisa y qué cuenta como roto
  auditar.py               reporte técnico puntual
  vigilar.py               vigilancia continua
  estado/                  estado e historial por cliente
reportes/                  los reportes generados
```

Ver `monitor/README.md` para el detalle de uso y de cómo dar de alta otro cliente.

## Configuración

Un solo secreto: **`GHL_API_KEY`**, un Private Integration Token de GoHighLevel con
permisos `contacts.readonly` y `contacts.write`. Va en Settings → Secrets and
variables → Actions. Nunca en un archivo.
