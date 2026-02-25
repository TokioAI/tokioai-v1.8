-- Script SQL para insertar datos de prueba para airesiliencehub.space

-- Limpiar datos anteriores de prueba
DELETE FROM waf_logs WHERE tenant_id = 2 AND ip LIKE '203.0.113.%';

-- Insertar logs de prueba
INSERT INTO waf_logs (timestamp, ip, method, uri, status, size, blocked, threat_type, tenant_id, created_at, raw_log, user_agent, referer) VALUES
(NOW() - INTERVAL '30 minutes', '203.0.113.110', 'GET', '/home', 200, 1500, false, NULL, 2, NOW() - INTERVAL '30 minutes', '{"host": "airesiliencehub.space"}'::jsonb, 'Mozilla/5.0', '-'),
(NOW() - INTERVAL '29 minutes', '203.0.113.111', 'GET', '/about', 200, 2000, false, NULL, 2, NOW() - INTERVAL '29 minutes', '{"host": "airesiliencehub.space"}'::jsonb, 'Mozilla/5.0', '-'),
(NOW() - INTERVAL '28 minutes', '203.0.113.112', 'POST', '/login', 200, 800, false, NULL, 2, NOW() - INTERVAL '28 minutes', '{"host": "airesiliencehub.space"}'::jsonb, 'Mozilla/5.0', '-'),
(NOW() - INTERVAL '27 minutes', '203.0.113.113', 'GET', '/products', 200, 3000, false, NULL, 2, NOW() - INTERVAL '27 minutes', '{"host": "airesiliencehub.space"}'::jsonb, 'Mozilla/5.0', '-'),
(NOW() - INTERVAL '26 minutes', '203.0.113.114', 'GET', '/blog', 200, 2500, false, NULL, 2, NOW() - INTERVAL '26 minutes', '{"host": "airesiliencehub.space"}'::jsonb, 'Mozilla/5.0', '-'),
(NOW() - INTERVAL '25 minutes', '203.0.113.120', 'GET', '/search?q=<script>alert(document.cookie)</script>', 403, 146, true, 'XSS', 2, NOW() - INTERVAL '25 minutes', '{"host": "airesiliencehub.space", "blocked": true}'::jsonb, 'python-requests/2.31.0', '-'),
(NOW() - INTERVAL '24 minutes', '203.0.113.121', 'GET', '/api/users?id=1 OR 1=1 UNION SELECT * FROM users', 403, 146, true, 'SQL Injection', 2, NOW() - INTERVAL '24 minutes', '{"host": "airesiliencehub.space", "blocked": true}'::jsonb, 'sqlmap/1.7', '-'),
(NOW() - INTERVAL '23 minutes', '203.0.113.122', 'GET', '/../../../../etc/passwd', 403, 146, true, 'Path Traversal', 2, NOW() - INTERVAL '23 minutes', '{"host": "airesiliencehub.space", "blocked": true}'::jsonb, 'curl/7.68.0', '-'),
(NOW() - INTERVAL '22 minutes', '203.0.113.123', 'GET', '/cmd.php?exec=cat /etc/passwd', 403, 146, true, 'Command Injection', 2, NOW() - INTERVAL '22 minutes', '{"host": "airesiliencehub.space", "blocked": true}'::jsonb, 'python-requests/2.31.0', '-'),
(NOW() - INTERVAL '21 minutes', '203.0.113.124', 'GET', '/contact', 200, 1800, false, NULL, 2, NOW() - INTERVAL '21 minutes', '{"host": "airesiliencehub.space"}'::jsonb, 'Mozilla/5.0', '-'),
(NOW() - INTERVAL '20 minutes', '203.0.113.125', 'GET', '/api/data', 200, 1200, false, NULL, 2, NOW() - INTERVAL '20 minutes', '{"host": "airesiliencehub.space"}'::jsonb, 'Mozilla/5.0', '-'),
(NOW() - INTERVAL '19 minutes', '203.0.113.130', 'GET', '/search?q=<img src=x onerror=alert(1)>', 403, 146, true, 'XSS', 2, NOW() - INTERVAL '19 minutes', '{"host": "airesiliencehub.space", "blocked": true}'::jsonb, 'python-requests/2.31.0', '-'),
(NOW() - INTERVAL '18 minutes', '203.0.113.131', 'GET', '/admin?id=1 UNION SELECT username, password FROM users', 403, 146, true, 'SQL Injection', 2, NOW() - INTERVAL '18 minutes', '{"host": "airesiliencehub.space", "blocked": true}'::jsonb, 'sqlmap/1.7', '-'),
(NOW() - INTERVAL '17 minutes', '203.0.113.132', 'GET', '/../../../var/www/html/config.php', 403, 146, true, 'Path Traversal', 2, NOW() - INTERVAL '17 minutes', '{"host": "airesiliencehub.space", "blocked": true}'::jsonb, 'curl/7.68.0', '-'),
(NOW() - INTERVAL '16 minutes', '203.0.113.133', 'POST', '/dashboard', 200, 2500, false, NULL, 2, NOW() - INTERVAL '16 minutes', '{"host": "airesiliencehub.space"}'::jsonb, 'Mozilla/5.0', '-'),
(NOW() - INTERVAL '15 minutes', '203.0.113.134', 'GET', '/settings', 200, 1500, false, NULL, 2, NOW() - INTERVAL '15 minutes', '{"host": "airesiliencehub.space"}'::jsonb, 'Mozilla/5.0', '-'),
(NOW() - INTERVAL '14 minutes', '203.0.113.140', 'GET', '/test?q=<svg onload=alert(1)>', 403, 146, true, 'XSS', 2, NOW() - INTERVAL '14 minutes', '{"host": "airesiliencehub.space", "blocked": true}'::jsonb, 'python-requests/2.31.0', '-'),
(NOW() - INTERVAL '13 minutes', '203.0.113.141', 'GET', '/search?q=" OR "1"="1', 403, 146, true, 'SQL Injection', 2, NOW() - INTERVAL '13 minutes', '{"host": "airesiliencehub.space", "blocked": true}'::jsonb, 'sqlmap/1.7', '-'),
(NOW() - INTERVAL '12 minutes', '203.0.113.142', 'GET', '/../../windows/win.ini', 403, 146, true, 'Path Traversal', 2, NOW() - INTERVAL '12 minutes', '{"host": "airesiliencehub.space", "blocked": true}'::jsonb, 'curl/7.68.0', '-'),
(NOW() - INTERVAL '11 minutes', '203.0.113.143', 'GET', '/api', 200, 900, false, NULL, 2, NOW() - INTERVAL '11 minutes', '{"host": "airesiliencehub.space"}'::jsonb, 'Mozilla/5.0', '-'),
(NOW() - INTERVAL '10 minutes', '203.0.113.144', 'GET', '/', 200, 2000, false, NULL, 2, NOW() - INTERVAL '10 minutes', '{"host": "airesiliencehub.space"}'::jsonb, 'Mozilla/5.0', '-');

-- Bypasses
INSERT INTO detected_bypasses (tenant_id, source_ip, attack_type, bypass_method, mitigated, detected_at, request_data, response_data)
VALUES 
(2, '203.0.113.250', 'XSS', 'Unicode encoding', false, NOW(), '{"host": "airesiliencehub.space", "uri": "/test?q=<script>alert(1)</script>"}'::jsonb, '{"host": "airesiliencehub.space", "uri": "/test?q=%u003Cscript%u003Ealert(1)%u003C/script%u003E", "status": 200}'::jsonb),
(2, '203.0.113.251', 'SQL Injection', 'Comment injection', true, NOW() - INTERVAL '1 hour', '{"host": "airesiliencehub.space", "uri": "/api?id=1--"}'::jsonb, '{"host": "airesiliencehub.space", "uri": "/api?id=1 OR 1=1--", "status": 200}'::jsonb);

-- Incidentes
INSERT INTO incidents (tenant_id, title, description, status, severity, incident_type, source_ip, detected_at)
VALUES 
(2, 'Múltiples ataques XSS desde 203.0.113.120', 'Se detectaron múltiples intentos de XSS desde la misma IP', 'open', 'high', 'persistent_attack', '203.0.113.120', NOW() - INTERVAL '25 minutes'),
(2, 'Bypass de SQL Injection detectado', 'Se detectó un bypass de SQL Injection usando encoding', 'open', 'critical', 'bypass', '203.0.113.251', NOW() - INTERVAL '1 hour');

