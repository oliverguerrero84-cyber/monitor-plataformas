# Monitoreo de plataformas de clientes

Vigila que el sitio de un cliente **funcione de verdad**, no solo que responda.

## Por qué no basta con un monitor de estante

Los servicios comunes revisan el código HTTP. Este sitio devuelve **HTTP 200
mostrando "Página no encontrada"**, y en un caso devolvía una imagen PNG en lugar
de la página del curso. Un monitor que solo mire el código reporta esas fallas
como éxito.

Este revisa además el **contenido**: busca frases que significan "cargó pero está
rota", tomadas de los reportes reales del equipo del cliente.

## Piezas

| Archivo | Para qué |
|---|---|
| `clientes/<nombre>.json` | Todo lo específico del cliente: sitio, páginas, frases, ids del CRM |
| `sitio.py` | Qué se revisa y qué cuenta como roto |
| `auditar.py` | Reporte técnico puntual, para entregar |
| `vigilar.py` | Vigilancia continua; avisa solo cuando algo cambia |

## Uso

```bash
python3 monitor/auditar.py --cliente ppdg --pasadas 4     # reporte
python3 monitor/vigilar.py --cliente ppdg --sin-avisar    # revisar sin avisar
python3 monitor/vigilar.py --cliente ppdg --probar        # alerta de prueba
python3 monitor/vigilar.py --cliente ppdg                 # revisión real
```

## Cómo avisa

El monitor **no manda mensajes**. Escribe el texto en un campo del contacto de
alerta del CRM y le pone una etiqueta; esa etiqueta dispara el workflow `[MON-1]`,
que manda el WhatsApp y el correo y luego **se quita la etiqueta** para que la
siguiente alerta pueda volver a dispararlo.

Avisa dos veces por incidente: cuando algo se rompe, y cuando se restablece — con
cuánto duró. Ese segundo aviso es el dato que hoy nadie tiene.

Si el CRM o el puente de WhatsApp fallan, la corrida sale con error y **GitHub
manda su propio correo**: un segundo canal que no depende de nada del proyecto.

## Para dar de alta otro cliente

1. Copiar `clientes/ppdg.json` y ajustar sitio, páginas y frases.
2. Crear en su subcuenta el contacto de alerta, el campo y el workflow.
3. Poner esos ids en el JSON nuevo.

## Configuración

Un solo secreto: **`GHL_API_KEY`**, un Private Integration Token con los permisos
`contacts.readonly` y `contacts.write`. Nada más — el monitor no toca workflows
ni oportunidades.

Va en Settings → Secrets and variables → Actions. Nunca en un archivo.
