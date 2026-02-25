"""
Spotify Tools - Herramientas para interactuar con la API de Spotify
Permite crear playlists personalizadas usando la API de Spotify.
Renueva tokens automáticamente usando refresh token.
"""
import os
import logging
import base64
import time
from typing import Dict, Any, Optional, List
from urllib import request as urlrequest
from urllib.error import URLError, HTTPError
import json
from pathlib import Path

logger = logging.getLogger(__name__)

# Configuración de Spotify API
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "f254b3f1b7014353aef6a5841817be7a")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "fc5e2483ebef4298a568ebbe44d99d2a")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback")
SPOTIFY_API_BASE_URL = "https://api.spotify.com/v1"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"

# Archivo para almacenar tokens (en el directorio del usuario o temporal)
TOKEN_STORAGE_FILE = os.getenv(
    "SPOTIFY_TOKEN_FILE",
    str(Path.home() / ".spotify_tokio_token.json")
)

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# Cache en memoria del token actual
_token_cache = {
    "access_token": None,
    "refresh_token": None,
    "expires_at": 0
}

def _load_token_storage() -> Dict[str, Any]:
    """Carga tokens almacenados desde archivo."""
    try:
        if os.path.exists(TOKEN_STORAGE_FILE):
            with open(TOKEN_STORAGE_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Error cargando tokens almacenados: {e}")
    return {}

def _save_token_storage(tokens: Dict[str, Any]) -> None:
    """Guarda tokens en archivo."""
    try:
        # Asegurar que el directorio existe
        os.makedirs(os.path.dirname(TOKEN_STORAGE_FILE) or '.', exist_ok=True)
        with open(TOKEN_STORAGE_FILE, 'w') as f:
            json.dump(tokens, f)
        # Proteger el archivo (solo lectura para el propietario)
        os.chmod(TOKEN_STORAGE_FILE, 0o600)
    except Exception as e:
        logger.warning(f"Error guardando tokens: {e}")

def _get_access_token() -> Optional[str]:
    """
    Obtiene un access token usando Client Credentials flow.
    Nota: Este token solo permite acceso a endpoints públicos.
    Para crear playlists, se necesita un token de usuario.
    """
    try:
        # Codificar credenciales en base64
        credentials = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        headers = {
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        data = "grant_type=client_credentials"
        
        if HAS_REQUESTS:
            response = requests.post(SPOTIFY_TOKEN_URL, headers=headers, data=data, timeout=10)
            if response.status_code == 200:
                token_data = response.json()
                return token_data.get("access_token")
            else:
                logger.warning(f"Error obteniendo token: {response.status_code} - {response.text}")
                return None
        else:
            req = urlrequest.Request(SPOTIFY_TOKEN_URL, data=data.encode(), headers=headers)
            with urlrequest.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    token_data = json.loads(resp.read().decode())
                    return token_data.get("access_token")
                else:
                    logger.warning(f"Error obteniendo token: {resp.status}")
                    return None
    except Exception as e:
        logger.error(f"Error en _get_access_token: {e}")
        return None

def _refresh_user_token(refresh_token: str) -> Optional[Dict[str, Any]]:
    """
    Renueva un access token usando el refresh token.
    Retorna dict con access_token, expires_in, y refresh_token (si se renueva).
    """
    try:
        credentials = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        headers = {
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        data = f"grant_type=refresh_token&refresh_token={refresh_token}"
        
        if HAS_REQUESTS:
            response = requests.post(SPOTIFY_TOKEN_URL, headers=headers, data=data, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Error renovando token: {response.status_code} - {response.text}")
                return None
        else:
            req = urlrequest.Request(SPOTIFY_TOKEN_URL, data=data.encode(), headers=headers)
            with urlrequest.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode())
                else:
                    logger.warning(f"Error renovando token: {resp.status}")
                    return None
    except Exception as e:
        logger.error(f"Error en _refresh_user_token: {e}")
        return None

def _get_user_access_token(user_token: Optional[str] = None, force_refresh: bool = False) -> Optional[str]:
    """
    Obtiene un access token de usuario, renovándolo automáticamente si es necesario.
    
    Prioridad:
    1. Token proporcionado como parámetro
    2. Token en cache (si no expiró)
    3. Token renovado usando refresh token
    4. Token de variable de entorno
    5. Client credentials (limitado)
    """
    # Si se proporciona token explícitamente, usarlo
    if user_token:
        return user_token
    
    current_time = time.time()
    
    # Verificar cache en memoria
    if not force_refresh and _token_cache["access_token"] and _token_cache["expires_at"] > current_time:
        return _token_cache["access_token"]
    
    # Cargar tokens almacenados
    stored = _load_token_storage()
    refresh_token = stored.get("refresh_token") or os.getenv("SPOTIFY_REFRESH_TOKEN", "").strip()
    stored_access_token = stored.get("access_token")
    stored_expires_at = stored.get("expires_at", 0)
    
    # Si hay refresh token, intentar renovar
    if refresh_token:
        logger.info("Renovando access token usando refresh token...")
        token_data = _refresh_user_token(refresh_token)
        
        if token_data:
            access_token = token_data.get("access_token")
            expires_in = token_data.get("expires_in", 3600)  # Default 1 hora
            new_refresh_token = token_data.get("refresh_token", refresh_token)  # Puede venir nuevo o mantener el anterior
            
            # Actualizar cache
            _token_cache["access_token"] = access_token
            _token_cache["refresh_token"] = new_refresh_token
            _token_cache["expires_at"] = current_time + expires_in - 60  # 1 minuto de margen
            
            # Guardar en archivo
            _save_token_storage({
                "access_token": access_token,
                "refresh_token": new_refresh_token,
                "expires_at": _token_cache["expires_at"]
            })
            
            logger.info("✅ Token renovado exitosamente")
            return access_token
        else:
            logger.warning("⚠️ No se pudo renovar el token. Puede que el refresh token haya expirado.")
    
    # Si hay token almacenado y no expiró, usarlo
    if stored_access_token and stored_expires_at > current_time:
        _token_cache["access_token"] = stored_access_token
        _token_cache["expires_at"] = stored_expires_at
        return stored_access_token
    
    # Intentar variable de entorno
    env_token = os.getenv("SPOTIFY_USER_ACCESS_TOKEN", "").strip()
    if env_token:
        return env_token
    
    # Fallback a client credentials (limitado)
    logger.warning("⚠️ No hay refresh token configurado. Usando client credentials (limitado para crear playlists)")
    return _get_access_token()

def _make_spotify_request(
    method: str,
    endpoint: str,
    access_token: str,
    data: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, str]] = None,
    retry_on_401: bool = True
) -> Dict[str, Any]:
    """
    Realiza una petición a la API de Spotify.
    Si recibe 401 (token expirado), intenta renovar el token automáticamente.
    """
    url = f"{SPOTIFY_API_BASE_URL}/{endpoint.lstrip('/')}"
    
    if params:
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        url = f"{url}?{query_string}"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        if HAS_REQUESTS:
            if method.upper() == "GET":
                response = requests.get(url, headers=headers, timeout=15)
            elif method.upper() == "POST":
                response = requests.post(url, headers=headers, json=data, timeout=15)
            elif method.upper() == "PUT":
                response = requests.put(url, headers=headers, json=data, timeout=15)
            elif method.upper() == "DELETE":
                response = requests.delete(url, headers=headers, timeout=15)
            else:
                return {"success": False, "error": f"Método HTTP no soportado: {method}"}
            
            # Si el token expiró (401) y tenemos refresh token, renovar y reintentar
            if response.status_code == 401 and retry_on_401:
                logger.info("Token expirado, renovando automáticamente...")
                new_token = _get_user_access_token(force_refresh=True)
                if new_token and new_token != access_token:
                    # Reintentar con el nuevo token
                    headers["Authorization"] = f"Bearer {new_token}"
                    if method.upper() == "GET":
                        response = requests.get(url, headers=headers, timeout=15)
                    elif method.upper() == "POST":
                        response = requests.post(url, headers=headers, json=data, timeout=15)
                    elif method.upper() == "PUT":
                        response = requests.put(url, headers=headers, json=data, timeout=15)
                    elif method.upper() == "DELETE":
                        response = requests.delete(url, headers=headers, timeout=15)
            
            if response.status_code in [200, 201, 204]:
                if response.content:
                    return {"success": True, "data": response.json()}
                return {"success": True, "data": {}}
            else:
                error_text = response.text
                logger.warning(f"Spotify API error {response.status_code}: {error_text}")
                return {"success": False, "error": f"HTTP {response.status_code}: {error_text}"}
        else:
            # Fallback usando urllib
            req_data = json.dumps(data).encode() if data else None
            req = urlrequest.Request(url, data=req_data, headers=headers, method=method.upper())
            with urlrequest.urlopen(req, timeout=15) as resp:
                if resp.status in [200, 201, 204]:
                    if resp.content:
                        return {"success": True, "data": json.loads(resp.read().decode())}
                    return {"success": True, "data": {}}
                else:
                    error_text = resp.read().decode()
                    logger.warning(f"Spotify API error {resp.status}: {error_text}")
                    return {"success": False, "error": f"HTTP {resp.status}: {error_text}"}
    except HTTPError as e:
        # Si es 401 y tenemos refresh token, intentar renovar
        if e.code == 401 and retry_on_401:
            logger.info("Token expirado (urllib), renovando automáticamente...")
            new_token = _get_user_access_token(force_refresh=True)
            if new_token and new_token != access_token:
                headers["Authorization"] = f"Bearer {new_token}"
                try:
                    req_data = json.dumps(data).encode() if data else None
                    req = urlrequest.Request(url, data=req_data, headers=headers, method=method.upper())
                    with urlrequest.urlopen(req, timeout=15) as resp:
                        if resp.status in [200, 201, 204]:
                            if resp.content:
                                return {"success": True, "data": json.loads(resp.read().decode())}
                            return {"success": True, "data": {}}
                except Exception as retry_error:
                    pass  # Continuar con el error original
        
        error_body = e.read().decode() if e.fp else str(e)
        logger.error(f"HTTP error en Spotify API: {error_body}")
        return {"success": False, "error": f"HTTP {e.code}: {error_body}"}
    except URLError as e:
        logger.error(f"URL error en Spotify API: {e}")
        return {"success": False, "error": f"Error de conexión: {str(e)}"}
    except Exception as e:
        logger.error(f"Error inesperado en Spotify API: {e}")
        return {"success": False, "error": f"Error inesperado: {str(e)}"}

async def tool_create_spotify_playlist(
    name: str,
    description: Optional[str] = None,
    public: bool = True,
    collaborative: bool = False,
    user_id: Optional[str] = None,
    access_token: Optional[str] = None,
    track_uris: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Crea una playlist en Spotify.
    
    Args:
        name: Nombre de la playlist (requerido)
        description: Descripción de la playlist (opcional)
        public: Si la playlist es pública (default: True)
        collaborative: Si la playlist es colaborativa (default: False)
        user_id: ID del usuario de Spotify (opcional, se obtiene del token si no se proporciona)
        access_token: Access token de usuario de Spotify (opcional, usa variable de entorno si no se proporciona)
        track_uris: Lista de URIs de tracks para agregar a la playlist (opcional, formato: spotify:track:ID)
    
    Returns:
        Dict con información de la playlist creada o error
    """
    try:
        # Obtener access token
        token = _get_user_access_token(access_token)
        if not token:
            return {
                "success": False,
                "error": "No se pudo obtener access token. Asegúrate de tener SPOTIFY_USER_ACCESS_TOKEN configurado o proporciona access_token."
            }
        
        # Obtener user_id si no se proporciona
        if not user_id:
            user_info = _make_spotify_request("GET", "/me", token)
            if not user_info.get("success"):
                return {
                    "success": False,
                    "error": f"No se pudo obtener el ID de usuario: {user_info.get('error', 'Error desconocido')}"
                }
            user_id = user_info["data"].get("id")
            if not user_id:
                return {
                    "success": False,
                    "error": "No se pudo obtener el ID de usuario del token proporcionado"
                }
        
        # Crear la playlist
        playlist_data = {
            "name": name,
            "public": public,
            "collaborative": collaborative
        }
        if description:
            playlist_data["description"] = description
        
        create_result = _make_spotify_request(
            "POST",
            f"/users/{user_id}/playlists",
            token,
            data=playlist_data
        )
        
        if not create_result.get("success"):
            return create_result
        
        playlist = create_result["data"]
        playlist_id = playlist.get("id")
        playlist_url = playlist.get("external_urls", {}).get("spotify", "")
        
        result = {
            "success": True,
            "playlist_id": playlist_id,
            "playlist_name": name,
            "playlist_url": playlist_url,
            "tracks_added": 0
        }
        
        # Agregar tracks si se proporcionaron
        if track_uris and playlist_id:
            # Filtrar URIs válidas
            valid_uris = [uri for uri in track_uris if uri.startswith("spotify:track:")]
            
            if valid_uris:
                # Spotify permite agregar hasta 100 tracks por request
                chunks = [valid_uris[i:i+100] for i in range(0, len(valid_uris), 100)]
                
                for chunk in chunks:
                    add_result = _make_spotify_request(
                        "POST",
                        f"/playlists/{playlist_id}/tracks",
                        token,
                        data={"uris": chunk}
                    )
                    if add_result.get("success"):
                        result["tracks_added"] += len(chunk)
                    else:
                        logger.warning(f"Error agregando tracks: {add_result.get('error')}")
                
                result["message"] = f"Playlist '{name}' creada con {result['tracks_added']} tracks"
            else:
                result["message"] = f"Playlist '{name}' creada (sin tracks, URIs inválidas)"
        else:
            result["message"] = f"Playlist '{name}' creada exitosamente"
        
        return result
        
    except Exception as e:
        logger.error(f"Error en tool_create_spotify_playlist: {e}")
        return {
            "success": False,
            "error": f"Error inesperado: {str(e)}"
        }

async def tool_search_spotify_tracks(
    query: str,
    limit: int = 20,
    access_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Busca tracks en Spotify.
    
    Args:
        query: Término de búsqueda
        limit: Número máximo de resultados (default: 20, máximo: 50)
        access_token: Access token (opcional, se renueva automáticamente si es necesario)
    
    Returns:
        Dict con lista de tracks encontrados
    """
    try:
        token = _get_user_access_token(access_token) or _get_access_token()
        if not token:
            return {
                "success": False,
                "error": "No se pudo obtener access token"
            }
        
        search_result = _make_spotify_request(
            "GET",
            "/search",
            token,
            params={
                "q": query,
                "type": "track",
                "limit": str(min(limit, 50))
            }
        )
        
        if not search_result.get("success"):
            return search_result
        
        tracks = search_result["data"].get("tracks", {}).get("items", [])
        
        # Formatear resultados
        formatted_tracks = []
        for track in tracks:
            artists = ", ".join([artist["name"] for artist in track.get("artists", [])])
            formatted_tracks.append({
                "name": track.get("name"),
                "artists": artists,
                "uri": track.get("uri"),
                "id": track.get("id"),
                "external_url": track.get("external_urls", {}).get("spotify", "")
            })
        
        return {
            "success": True,
            "query": query,
            "tracks": formatted_tracks,
            "total": len(formatted_tracks)
        }
        
    except Exception as e:
        logger.error(f"Error en tool_search_spotify_tracks: {e}")
        return {
            "success": False,
            "error": f"Error inesperado: {str(e)}"
        }

async def tool_set_spotify_refresh_token(refresh_token: str) -> Dict[str, Any]:
    """
    Configura el refresh token de Spotify para renovación automática.
    Solo necesitas hacerlo una vez, luego el sistema renueva tokens automáticamente.
    
    Args:
        refresh_token: Refresh token de Spotify obtenido del flujo OAuth2
    
    Returns:
        Dict con resultado de la configuración
    """
    try:
        # Probar el refresh token renovando un access token
        token_data = _refresh_user_token(refresh_token)
        
        if not token_data:
            return {
                "success": False,
                "error": "El refresh token proporcionado no es válido o expiró"
            }
        
        access_token = token_data.get("access_token")
        expires_in = token_data.get("expires_in", 3600)
        new_refresh_token = token_data.get("refresh_token", refresh_token)
        
        # Guardar tokens
        current_time = time.time()
        tokens = {
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "expires_at": current_time + expires_in - 60
        }
        
        _save_token_storage(tokens)
        
        # Actualizar cache
        _token_cache.update(tokens)
        
        return {
            "success": True,
            "message": "✅ Refresh token configurado exitosamente. Los tokens se renovarán automáticamente.",
            "expires_in": expires_in
        }
        
    except Exception as e:
        logger.error(f"Error en tool_set_spotify_refresh_token: {e}")
        return {
            "success": False,
            "error": f"Error configurando refresh token: {str(e)}"
        }
