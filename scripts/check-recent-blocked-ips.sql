-- Verificar bloqueos recientes en blocked_ips
-- Mostrar todos los campos relevantes

SELECT 
    ip,
    blocked_at,
    threat_type,
    classification_source,
    blocked_by,
    active,
    expires_at,
    reason,
    severity
FROM blocked_ips 
WHERE blocked_at > NOW() - INTERVAL '48 hours'
ORDER BY blocked_at DESC
LIMIT 30;

-- Verificar bloqueos por classification_source
SELECT 
    COALESCE(classification_source, blocked_by, 'NULL') as source,
    COUNT(*) as count
FROM blocked_ips 
WHERE blocked_at > NOW() - INTERVAL '48 hours'
AND active = TRUE
AND (expires_at IS NULL OR expires_at > NOW())
GROUP BY COALESCE(classification_source, blocked_by, 'NULL')
ORDER BY count DESC;







