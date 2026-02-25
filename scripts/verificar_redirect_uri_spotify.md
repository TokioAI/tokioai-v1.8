# Cómo verificar y agregar Redirect URI en Spotify

## El problema
El error `INVALID_CLIENT: Invalid redirect URI` significa que el redirect URI que estás usando no está registrado en tu aplicación de Spotify.

## Solución

### Paso 1: Ir al Dashboard de Spotify
1. Ve a: https://developer.spotify.com/dashboard/applications
2. Inicia sesión con tu cuenta de Spotify
3. Selecciona tu aplicación (Client ID: `f254b3f1b7014353aef6a5841817be7a`)

### Paso 2: Agregar Redirect URI
1. Haz clic en "Edit Settings" (o "Configuración")
2. Busca la sección "Redirect URIs"
3. Haz clic en "Add URI"
4. Agrega uno de estos (o el que prefieras):
   - `http://localhost:3000/callback`
   - `http://localhost:8888/callback`
   - `http://localhost/callback`
   - `http://YOUR_IP_ADDRESS:3000/callback`

### Paso 3: Guardar
1. Haz clic en "Add" o "Save"
2. Espera unos segundos para que se actualice

### Paso 4: Usar el script mejorado
Ahora ejecuta el script mejorado que te permite elegir el redirect URI:

```bash
./scripts/configurar_spotify_refresh_token_v2.sh
```

Este script te preguntará qué redirect URI tienes registrado y lo usará.

## Redirect URIs comunes que puedes usar

- `http://localhost:3000/callback` (más común)
- `http://localhost:8888/callback`
- `http://localhost/callback`
- `http://YOUR_IP_ADDRESS:3000/callback`

**Importante**: El redirect URI debe coincidir EXACTAMENTE (incluyendo http/https, puerto, y ruta).

## Alternativa: Usar la consola web de Spotify

Si prefieres no configurar redirect URIs, puedes usar directamente la consola web:

1. Ve a: https://developer.spotify.com/console/post-playlists/
2. Haz clic en "Get Token"
3. Selecciona los scopes: `playlist-modify-public` y `playlist-modify-private`
4. Copia el token generado
5. Úsalo temporalmente (expira en 1 hora)

Pero para renovación automática, necesitas el refresh token usando el script.
