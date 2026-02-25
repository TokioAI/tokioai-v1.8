# Spotify Playlist Creator

## Descripción
Crea playlists personalizadas en Spotify a la medida del usuario. Permite buscar canciones, crear playlists con nombre y descripción personalizados, y agregar tracks específicos.

## Parámetros
- name (requerido): Nombre de la playlist a crear
- description (opcional): Descripción de la playlist
- public (opcional, default: true): Si la playlist es pública o privada
- query (opcional): Término de búsqueda para encontrar canciones (artista, canción, álbum)
- track_uris (opcional): Lista de URIs de tracks específicos en formato spotify:track:ID

## Categoría
Music

## Herramientas
create_spotify_playlist, search_spotify_tracks

## Instrucciones
Cuando el usuario pida crear una playlist en Spotify:

1. **Si el usuario menciona canciones específicas o quiere buscar:**
   - Primero usa `search_spotify_tracks` con el término de búsqueda para encontrar las canciones
   - Extrae las URIs de los tracks encontrados (campo "uri" en los resultados)
   - Luego usa `create_spotify_playlist` con el nombre y las URIs encontradas

2. **Si el usuario solo pide crear una playlist sin canciones específicas:**
   - Usa directamente `create_spotify_playlist` con el nombre proporcionado
   - Si el usuario menciona un tema o género, puedes buscar tracks relacionados primero

3. **Configuración de credenciales:**
   - Las credenciales de Spotify (Client ID y Client Secret) ya están configuradas
   - Para crear playlists, se necesita un access token de usuario de Spotify
   - El token puede proporcionarse como parámetro `access_token` o configurarse en la variable de entorno `SPOTIFY_USER_ACCESS_TOKEN`
   - Si no se proporciona token de usuario, la herramienta intentará usar client credentials (limitado)

4. **Formato de URIs:**
   - Las URIs de tracks deben estar en formato: `spotify:track:ID`
   - Ejemplo: `spotify:track:4iV5W9uYEdYUVa79Axb7Rh`

5. **Flujo recomendado:**
   - Usuario: "crea una playlist de rock"
   - Paso 1: `search_spotify_tracks(query="rock", limit=20)`
   - Paso 2: Extraer URIs de los resultados
   - Paso 3: `create_spotify_playlist(name="Mi Playlist de Rock", track_uris=[...])`

## Ejemplos
- "crea una playlist llamada 'Música para trabajar'" → create_spotify_playlist(name="Música para trabajar")
- "hazme una playlist de rock" → search_spotify_tracks(query="rock", limit=20) → create_spotify_playlist(name="Rock", track_uris=[URIs encontradas])
- "crea una playlist de música electrónica llamada 'EDM Mix'" → search_spotify_tracks(query="electronic music", limit=30) → create_spotify_playlist(name="EDM Mix", description="Música electrónica", track_uris=[URIs])
- "crea una playlist privada de jazz" → search_spotify_tracks(query="jazz", limit=20) → create_spotify_playlist(name="Jazz", public=false, track_uris=[URIs])

## Notas Importantes
- ✅ **Renovación automática**: Los tokens se renuevan automáticamente si hay un refresh token configurado
- Para configurar el refresh token (solo una vez):
  - Ejecuta: `./scripts/configurar_spotify_refresh_token.sh`
  - O usa la herramienta: `set_spotify_refresh_token(refresh_token="tu_refresh_token")`
- Una vez configurado el refresh token, no necesitas preocuparte por tokens expirados
- El sistema detecta cuando un token expira y lo renueva automáticamente antes de cada petición
- Si no hay refresh token configurado, la herramienta intentará usar client credentials (limitado para crear playlists)
