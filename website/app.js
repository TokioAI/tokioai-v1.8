(function () {
  /* ─── ANIMATED SPIRAL LOGO (Fibonacci / Geometric) ─── */
  function drawSpiralLogo(container) {
    container.innerHTML = `
      <div class="glow-bg"></div>
      <svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg" style="overflow:visible">
        <defs>
          <filter id="glow"><feGaussianBlur stdDeviation="2.5" result="c"/><feMerge><feMergeNode in="c"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
          <filter id="glowS"><feGaussianBlur stdDeviation="4" result="c"/><feMerge><feMergeNode in="c"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
          <linearGradient id="spiralGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#00ffc8" stop-opacity="0"/>
            <stop offset="50%" stop-color="#00d4ff" stop-opacity="1"/>
            <stop offset="100%" stop-color="#7b5ea7" stop-opacity="0.6"/>
          </linearGradient>
        </defs>
        <g class="ring-1"><polygon points="100,18 174,59 174,141 100,182 26,141 26,59" fill="none" stroke="#00ffc8" stroke-width="1" stroke-dasharray="8 4" opacity="0.4" filter="url(#glow)"/></g>
        <g class="ring-2"><circle cx="100" cy="100" r="68" fill="none" stroke="#7b5ea7" stroke-width="1" stroke-dasharray="3 9" opacity="0.6" filter="url(#glow)"/></g>
        <g class="ring-3"><rect x="44" y="44" width="112" height="112" rx="4" fill="none" stroke="#00d4ff" stroke-width="0.8" stroke-dasharray="5 6" opacity="0.35" filter="url(#glow)"/></g>
        <g class="ring-4"><circle cx="100" cy="100" r="52" fill="none" stroke="#ff6b9d" stroke-width="0.8" stroke-dasharray="2 6" opacity="0.4" filter="url(#glow)"/></g>
        <g class="ring-5"><polygon points="100,62 131,78 138,112 117,138 83,138 62,112 69,78" fill="none" stroke="#00ffc8" stroke-width="0.8" stroke-dasharray="4 5" opacity="0.3" filter="url(#glow)"/></g>
        <g class="spiral-path"><path d="M 100 100 Q 100 88, 110 84 Q 126 80, 130 93 Q 136 112, 120 124 Q 100 138, 82 126 Q 62 112, 68 88 Q 76 64, 100 60 Q 130 56, 146 78 Q 158 100, 148 124 Q 136 150, 110 158 Q 80 164, 60 146" fill="none" stroke="url(#spiralGrad)" stroke-width="2" stroke-linecap="round" opacity="0.9" filter="url(#glow)"/></g>
        <g class="orbit-dot"><circle cx="100" cy="18" r="3.5" fill="#00ffc8" filter="url(#glowS)"/></g>
        <g class="orbit-dot-2"><circle cx="168" cy="100" r="2.5" fill="#7b5ea7" filter="url(#glowS)"/></g>
        <g class="orbit-dot-3"><circle cx="100" cy="48" r="2" fill="#ff6b9d" filter="url(#glowS)"/></g>
        <g class="core"><polygon points="100,86 112,107 88,107" fill="none" stroke="#00ffc8" stroke-width="1.5" opacity="0.8" filter="url(#glow)"/><circle cx="100" cy="100" r="5" fill="#00ffc8" opacity="0.9" filter="url(#glowS)"/><circle cx="100" cy="100" r="2" fill="#ffffff"/></g>
      </svg>`;
  }

  document.querySelectorAll('.spiral-logo').forEach(drawSpiralLogo);

  /* ─── PARTICLE CANVAS ─── */
  var canvas = document.getElementById('particleCanvas');
  if (canvas) {
    var ctx = canvas.getContext('2d');
    var particles = [];
    var PARTICLE_COUNT = 60;

    function resizeCanvas() {
      var hero = canvas.parentElement;
      canvas.width = hero.offsetWidth;
      canvas.height = hero.offsetHeight;
    }

    function createParticle() {
      return {
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * 0.4,
        vy: (Math.random() - 0.5) * 0.4,
        r: Math.random() * 1.5 + 0.5,
        o: Math.random() * 0.4 + 0.1,
        color: ['#00ffc8', '#7b5ea7', '#00d4ff'][Math.floor(Math.random() * 3)]
      };
    }

    function initParticles() {
      particles = [];
      for (var i = 0; i < PARTICLE_COUNT; i++) particles.push(createParticle());
    }

    function drawParticles() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (var i = 0; i < particles.length; i++) {
        var p = particles[i];
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < 0 || p.x > canvas.width) p.vx *= -1;
        if (p.y < 0 || p.y > canvas.height) p.vy *= -1;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = p.color;
        ctx.globalAlpha = p.o;
        ctx.fill();
        // Draw connections
        for (var j = i + 1; j < particles.length; j++) {
          var q = particles[j];
          var dx = p.x - q.x, dy = p.y - q.y;
          var dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 120) {
            ctx.beginPath();
            ctx.moveTo(p.x, p.y);
            ctx.lineTo(q.x, q.y);
            ctx.strokeStyle = '#00ffc8';
            ctx.globalAlpha = (1 - dist / 120) * 0.08;
            ctx.stroke();
          }
        }
      }
      ctx.globalAlpha = 1;
      requestAnimationFrame(drawParticles);
    }

    resizeCanvas();
    initParticles();
    drawParticles();
    window.addEventListener('resize', function () { resizeCanvas(); initParticles(); });
  }

  /* ─── TYPING EFFECT ─── */
  var typingEl = document.getElementById('heroTyping');
  if (typingEl) {
    var phrases_en = [
      'Execute, don\'t chat.',
      'The AI agent that acts.',
      '30+ tools. 26 WAF signatures.',
      'Deploy. Protect. Operate.',
      'Think \u2192 Act \u2192 Observe \u2192 Learn.'
    ];
    var phrases_es = [
      'Ejecuta, no chatea.',
      'El agente de IA que actua.',
      '30+ herramientas. 26 firmas WAF.',
      'Despliega. Protege. Opera.',
      'Piensa \u2192 Actua \u2192 Observa \u2192 Aprende.'
    ];
    var phraseIdx = 0, charIdx = 0, deleting = false;
    var currentLang = 'en';

    function getPhrases() {
      return currentLang === 'es' ? phrases_es : phrases_en;
    }

    function typeLoop() {
      var phrases = getPhrases();
      var phrase = phrases[phraseIdx % phrases.length];
      if (!deleting) {
        typingEl.textContent = phrase.substring(0, charIdx + 1);
        charIdx++;
        if (charIdx >= phrase.length) {
          deleting = true;
          setTimeout(typeLoop, 2000);
          return;
        }
        setTimeout(typeLoop, 50 + Math.random() * 30);
      } else {
        typingEl.textContent = phrase.substring(0, charIdx);
        charIdx--;
        if (charIdx < 0) {
          deleting = false;
          charIdx = 0;
          phraseIdx++;
          setTimeout(typeLoop, 400);
          return;
        }
        setTimeout(typeLoop, 25);
      }
    }
    setTimeout(typeLoop, 800);
  }

  /* ─── SCROLL ANIMATIONS (IntersectionObserver) ─── */
  var animEls = document.querySelectorAll('.anim');
  if ('IntersectionObserver' in window) {
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add('visible');
          obs.unobserve(e.target);
        }
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });
    animEls.forEach(function (el) { obs.observe(el); });
  } else {
    animEls.forEach(function (el) { el.classList.add('visible'); });
  }

  /* ─── COUNTER ANIMATION ─── */
  var counters = document.querySelectorAll('[data-count]');
  if ('IntersectionObserver' in window) {
    var counterObs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          var el = e.target;
          var target = parseInt(el.getAttribute('data-count'), 10);
          var current = 0;
          var step = Math.max(1, Math.floor(target / 30));
          var timer = setInterval(function () {
            current += step;
            if (current >= target) { current = target; clearInterval(timer); }
            el.textContent = current;
          }, 40);
          counterObs.unobserve(el);
        }
      });
    }, { threshold: 0.5 });
    counters.forEach(function (el) { counterObs.observe(el); });
  }

  /* ─── TOPBAR SCROLL SHADOW ─── */
  var topbar = document.getElementById('topbar');
  window.addEventListener('scroll', function () {
    if (topbar) topbar.classList.toggle('scrolled', window.scrollY > 10);
  });

  /* ─── SCROLL TO TOP ─── */
  var scrollBtn = document.getElementById('scrollTop');
  if (scrollBtn) {
    window.addEventListener('scroll', function () {
      scrollBtn.classList.toggle('visible', window.scrollY > 400);
    });
    scrollBtn.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  /* ─── HAMBURGER MENU ─── */
  var hamburger = document.getElementById('hamburger');
  var mainNav = document.getElementById('mainNav');
  if (hamburger && mainNav) {
    hamburger.addEventListener('click', function () {
      var isOpen = mainNav.classList.toggle('mobile-open');
      hamburger.classList.toggle('open', isOpen);
      hamburger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      document.body.style.overflow = isOpen ? 'hidden' : '';
    });
    mainNav.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', function () {
        mainNav.classList.remove('mobile-open');
        hamburger.classList.remove('open');
        hamburger.setAttribute('aria-expanded', 'false');
        document.body.style.overflow = '';
      });
    });
  }

  /* ─── DEMO VIDEO CONTROLS ─── */
  document.querySelectorAll('.demo-play').forEach(function (btn) {
    var wrap = btn.closest('.demo-video-wrap');
    var video = wrap.querySelector('video');
    btn.addEventListener('click', function () {
      if (video.paused) {
        video.play();
        btn.classList.add('hidden');
      }
    });
    video.addEventListener('click', function () {
      if (!video.paused) {
        video.pause();
        btn.classList.remove('hidden');
      }
    });
    video.addEventListener('ended', function () {
      btn.classList.remove('hidden');
    });
  });

  /* ─── i18n ─── */
  var I18N = {
    en: {
      nav_demos: 'Demos',
      nav_features: 'Features',
      nav_tools: 'Tools',
      nav_waf: 'WAF & SOC',
      nav_arch: 'Architecture',
      nav_sec: 'Security',
      nav_quickstart: 'Quickstart',
      kicker: 'Autonomous AI Agent Framework',
      hero_subtitle: 'TokioAI is an autonomous AI agent that executes \u2014 not just chats. 30+ built-in tools, production-grade WAF with 26 signatures, real-time SOC dashboard, multi-LLM support (Claude, GPT-4, Gemini), Telegram bot with vision & voice, GCP auto-deploy, and infrastructure-as-code. Control everything from your terminal, Telegram, or REST API.',
      hero_sublabel: 'Execute, Don\'t Chat',
      cta_start: 'Get Started',
      cta_github: 'View on GitHub',
      demo_title: 'See TokioAI in Action',
      demo_lead: 'Real footage of the autonomous agent detecting, analyzing, and blocking cyber threats \u2014 all in real time.',
      demo_waf_label: 'WAF & SOC Dashboard',
      demo_waf_desc: 'Supreme SOC Dashboard v3: blocked IPs, live traffic, OWASP breakdown, world attack map, heatmap, and real-time threat feed with multi-phase correlation.',
      demo_tg_label: 'Telegram Bot \u2014 Live Ops',
      demo_tg_desc: 'Autonomous threat analysis via Telegram: multi-phase attack detection, IP profiling (ASN, country, risk score), automatic blocking, and WiFi router security audit \u2014 all from a single chat.',
      stat_tools: 'Built-in Tools',
      stat_sigs: 'WAF Signatures',
      stat_llm: 'LLM Providers',
      stat_behav: 'Behavioral Rules',
      stat_sec: 'Security Layers',
      stat_iface: 'Interfaces',
      feat_title: 'What Makes TokioAI Different',
      feat_lead: 'Not another chatbot. An autonomous agent that thinks, acts, observes, and learns. Multi-round tool execution with up to 10 consecutive operations per message.',
      f1_title: 'Autonomous Agent Loop',
      f1_body: 'Think \u2192 Act \u2192 Observe \u2192 Learn. The agent chains multi-step tool operations, handles errors with retries, learns from failures to avoid repeating them, and requires confirmation for dangerous actions. Up to 10 tool rounds per message with a 10-minute execution timeout.',
      f2_title: 'Multi-LLM with Auto-Fallback',
      f2_body: 'Supports Anthropic Claude (Opus 4, Sonnet 4), OpenAI GPT (GPT-4o, o1, o3), and Google Gemini (2.0 Flash, Pro). Automatic fallback between providers ensures zero downtime. Configure your preferred chain in .env.',
      f3_title: 'Telegram Bot \u2014 Full Multimedia',
      f3_body: 'Not just text. Process images with Vision API, transcribe voice messages (Gemini + Whisper), analyze documents (PDF, DOCX, code), extract YouTube metadata, generate and send files (PDF, CSV, PPTX). ACL security with owner-only admin commands.',
      f4_title: 'Production WAF \u2014 26 Signatures',
      f4_body: 'Enterprise-grade WAF engine with 26 regex signatures detecting SQLi, XSS, RCE, LFI, SSRF, Log4Shell, XXE, SSTI, CRLF, NoSQL injection, HTTP smuggling, deserialization attacks, and more. Plus 7 behavioral rules for anomaly detection. Instant first-hit blocking for critical threats.',
      f5_title: 'Supreme SOC Dashboard',
      f5_body: 'Real-time SSE attack feed, world attack map with GeoIP, OWASP Top 10 breakdown, kill chain visualization, attack heatmap (hour x day), threat intelligence with AbuseIPDB, IP reputation tracking, signature monitor, and CSV export. Cyberpunk dark theme with JWT auth.',
      f6_title: 'One-Command GCP Deploy',
      f6_body: 'Deploy the entire stack on Google Cloud with a single natural language command. Creates VPC, firewall rules, static IP, VM, 7 Docker containers, SSL certificates, and DNS. Destroy everything with another command. Uses Google Cloud Python SDK directly.',
      f7_title: '30+ Built-in Tools',
      f7_body: 'System (bash, python, file I/O), Docker management, PostgreSQL queries, GCP compute & WAF, SSH host control, IoT & Home Assistant, router control (OpenWrt), DNS management, tunnel management, task orchestration, document generation, and more.',
      f8_title: 'Error Learning & Memory',
      f8_body: 'Cross-session persistent memory (SOUL.md + MEMORY.md). The agent remembers your preferences, learned facts, and past failures. Error learner avoids repeating mistakes. Plugin system for custom tools via workspace/plugins/.',
      f9_title: 'Container Watchdog & Self-Heal',
      f9_body: 'Automatic health monitoring of all Docker containers. Detects unhealthy or crashed services and auto-restarts them. Logs all events. Self-heal tool available for manual container recovery and diagnostics.',
      tools_title: '30+ Tools in 15 Categories',
      tools_lead: 'Every tool the agent needs to manage infrastructure, security, deployments, and operations autonomously.',
      waf_title: 'WAF & SOC Engine \u2014 Deep Dive',
      waf_lead: 'A production-grade security pipeline processing every HTTP request through multiple analysis layers. 26 signatures, 7 behavioral rules, honeypot detection, IP reputation, and multi-phase attack correlation.',
      waf_s1_title: 'Traffic Ingestion',
      waf_s1_body: 'Nginx reverse proxy captures every HTTP/HTTPS request with rate limiting (general: 10r/s, login: 2r/m, API: 30r/s). A log processor tails access logs in real-time and streams structured JSON events to Apache Kafka.',
      waf_s2_title: '26 WAF Signatures + 7 Behavioral Rules',
      waf_s2_body: 'Injection (13): SQLi, XSS, Command Injection, XXE, NoSQL, SSTI, CRLF, Log4Shell, LDAP. Access Control (3): Path Traversal/LFI, Scanner Detection, WebSocket Hijack. Plus: SSRF, Brute Force, HTTP Smuggling, Deserialization, Cryptominer, API Abuse, Exposed Configs. Behavioral: Recon, Exploit Attempts, Malformed Requests, Brute Force, Slow Attacks, Data Exfiltration.',
      waf_s3_title: 'Honeypot & IP Reputation',
      waf_s3_body: 'Fake endpoints (/wp-admin, /.env, /phpmyadmin) instantly identify attackers (WAF-5001, 0.99 confidence). Persistent IP reputation scoring in PostgreSQL tracks attack history per IP. GeoIP via DB-IP Lite for geographic threat intelligence.',
      waf_s4_title: 'Multi-Phase Attack Correlation',
      waf_s4_body: 'Detects attack chains: Recon \u2192 Probe \u2192 Exploit \u2192 Exfiltration. Groups same-IP attacks within 600s windows into episodes. Severity auto-escalates based on event count, types, and attack phases. OWASP Top 10 2021 classification for every threat.',
      waf_s5_title: 'Instant Blocking & Auto-Response',
      waf_s5_body: 'Tier 1: Instant block on critical signatures (confidence \u2265 0.90) \u2014 first hit, no waiting. Tier 2: Episode-based block after 3+ attack episodes. Tier 3: Rate-limit block at 40 req/5min threshold. Nginx blocklist updated with zero-downtime reload via sidecar container. 24h default block duration.',
      waf_s6_title: 'Supreme SOC Dashboard',
      waf_s6_body: 'Real-time SSE attack feed, world attack map, OWASP breakdown, kill chain visualization, attack heatmap (hour \u00d7 day), AbuseIPDB threat intelligence, signature monitor with hit counts, IP reputation tracking, CSV export, and cyberpunk dark theme. JWT authentication with full audit trail in PostgreSQL.',
      arch_title: 'System Architecture',
      arch_lead: 'Two deployment stacks working together \u2014 the AI Agent and the WAF/SOC infrastructure.',
      arch_1_title: 'TokioAI Agent Engine',
      arch_1_body: 'FastAPI service with async multi-round agent loop (Think \u2192 Act \u2192 Observe \u2192 Learn). Multi-LLM support with automatic fallback (Claude, GPT-4, Gemini). 30+ tools, error learning, persistent workspace memory, prompt guard security, and WebSocket interactive sessions. REST API + CLI interfaces.',
      arch_2_title: 'Telegram Bot',
      arch_2_body: 'Full multimedia Telegram interface: text, images (Vision API), voice (Gemini + Whisper), documents (PDF, DOCX, code), file generation (PDF, CSV, PPTX), YouTube metadata. ACL security with owner-only admin commands. Retry logic for network resilience.',
      arch_3_title: 'PostgreSQL',
      arch_3_body: 'Persistent storage for session memory, workspace data, user preferences, error learning history, prompt guard audit logs, and WAF events. Volumes for data persistence across container restarts.',
      int_title: '3 Interfaces, Infinite Control',
      int_lead: 'Control TokioAI from anywhere: your terminal, a REST API, or Telegram.',
      int_cli_title: 'CLI (Terminal)',
      int_cli_body: 'Interactive terminal with Rich formatting, real-time tool execution indicators, syntax highlighting, and pretty output. Full conversation sessions.',
      int_api_title: 'REST API + WebSocket',
      int_api_body: 'FastAPI server with /chat, /health, /stats, /tools, /sessions endpoints. WebSocket for interactive sessions. API key authentication and rate limiting.',
      int_tg_title: 'Telegram Bot',
      int_tg_body: 'Full multimedia: text, images (Vision), voice (Whisper), documents, file generation. YouTube support. ACL security. Owner-only admin: /allow, /deny, /acl.',
      sec_title: '3-Layer Security Architecture',
      sec_lead: 'Security isn\'t a feature \u2014 it\'s the foundation. Three independent layers protect every interaction from prompt to execution.',
      sec_1_title: 'Prompt Guard',
      sec_1_body: 'WAF for LLM prompts. Detects injection attacks BEFORE reaching the model: role override attempts, system prompt extraction, delimiter injection, encoding attacks (base64/hex), and tool abuse patterns. Full audit logging.',
      sec_2_title: 'Input Sanitizer',
      sec_2_body: 'Blocks dangerous commands BEFORE tool execution: reverse shells (nc -e, bash -i), crypto miners, fork bombs, destructive commands (rm -rf /, mkfs, dd), SQL injection, and path traversal attempts.',
      sec_3_title: 'Secure Channel',
      sec_3_body: 'API key authentication (Bearer token / X-API-Key), rate limiting per client (60 req/min), Telegram ACL with owner-only admin commands. JWT for dashboard. Zero hardcoded secrets \u2014 everything from environment variables.',
      sec_4_title: 'Action Confirmations',
      sec_4_body: 'Dangerous actions require explicit confirmation. Conservative defaults prevent accidental destruction.',
      sec_5_title: 'No Secrets in Code',
      sec_5_body: 'All secrets from .env. Comprehensive .gitignore. Zero hardcoded credentials.',
      sec_6_title: 'Shell Control',
      sec_6_body: 'HOST_CONTROL_ALLOW_RUN=false by default. SSH key-based auth only. All remote commands require confirmation.',
      gcp_title: 'GCP Deployment \u2014 One Command',
      gcp_lead: 'Tell TokioAI to deploy and everything is created automatically. Tell it to destroy and everything is cleaned up.',
      gcp_what_title: 'What Gets Created',
      gcp_w1: 'VPC Network + Subnet + Firewall Rules',
      gcp_w2: 'Static External IP for stable DNS',
      gcp_w3: 'Compute Engine VM (e2-medium) + Ubuntu + Docker',
      gcp_w4: 'SSL via Let\'s Encrypt with auto-renewal',
      gcp_w5: 'Nginx WAF Proxy with 26 signatures',
      gcp_w6: 'Kafka + Zookeeper event pipeline',
      gcp_w7: 'PostgreSQL with WAF schema',
      gcp_w8: 'Real-time ML threat processor',
      gcp_w9: 'SOC Dashboard with JWT auth',
      gcp_w10: 'Dynamic blocklist sidecar',
      gcp_w11: 'DNS configuration (Hostinger API)',
      gcp_ops_title: 'Natural Language Operations',
      qs_title: 'Quickstart \u2014 Up in 3 Steps',
      qs_lead: 'Works on any Linux machine with Docker. Raspberry Pi, laptop, server, or cloud VM.',
      qs_1_title: 'Clone & Configure',
      qs_2_title: 'Start the Stack',
      qs_3_title: 'Use TokioAI',
      qs_deploy_title: '3 Deployment Modes',
      qs_deploy_body: 'Full Local: Everything on your machine (dev, testing, Raspberry Pi). Hybrid: Agent local, WAF/Kafka/DB in cloud. Full Cloud: Everything on GCP. Maximum availability.',
      tech_title: 'Technology Stack',
      lic_title: 'Open Source (GPLv3)',
      lic_lead: 'TokioAI is free and open source under GNU GPL v3.0.',
      lic_1_title: 'Use & Modify',
      lic_1_body: 'Use, study, modify and redistribute freely for any purpose.',
      lic_2_title: 'Share Alike',
      lic_2_body: 'If you distribute, share your source under GPLv3.',
      lic_3_title: 'As Is',
      lic_3_body: 'Provided without warranty. See LICENSE for full terms.',
      footer_copy: 'Copyright \u00a9 2026 TokioAI \u2014 GPLv3 \u00b7 Tokio AI Security Research',
    },
    es: {
      nav_demos: 'Demos',
      nav_features: 'Funciones',
      nav_tools: 'Tools',
      nav_waf: 'WAF & SOC',
      nav_arch: 'Arquitectura',
      nav_sec: 'Seguridad',
      nav_quickstart: 'Inicio',
      kicker: 'Framework de Agente IA Aut\u00f3nomo',
      hero_subtitle: 'TokioAI es un agente IA aut\u00f3nomo que ejecuta \u2014 no solo chatea. 30+ herramientas, WAF de producci\u00f3n con 26 firmas, dashboard SOC en tiempo real, soporte multi-LLM (Claude, GPT-4, Gemini), bot de Telegram con visi\u00f3n y voz, deploy autom\u00e1tico en GCP e infraestructura como c\u00f3digo. Control\u00e1 todo desde tu terminal, Telegram o REST API.',
      hero_sublabel: 'Ejecuta, No Chatea',
      cta_start: 'Comenzar',
      cta_github: 'Ver en GitHub',
      demo_title: 'Mir\u00e1 TokioAI en Acci\u00f3n',
      demo_lead: 'Footage real del agente aut\u00f3nomo detectando, analizando y bloqueando amenazas cibern\u00e9ticas \u2014 todo en tiempo real.',
      demo_waf_label: 'Dashboard WAF & SOC',
      demo_waf_desc: 'Dashboard SOC Supreme v3: IPs bloqueadas, tr\u00e1fico en vivo, breakdown OWASP, mapa mundial de ataques, heatmap y feed de amenazas en tiempo real con correlaci\u00f3n multi-fase.',
      demo_tg_label: 'Bot Telegram \u2014 Ops en Vivo',
      demo_tg_desc: 'An\u00e1lisis aut\u00f3nomo de amenazas v\u00eda Telegram: detecci\u00f3n de ataques multi-fase, perfilado de IP (ASN, pa\u00eds, risk score), bloqueo autom\u00e1tico y auditor\u00eda de seguridad WiFi del router \u2014 todo desde un solo chat.',
      stat_tools: 'Herramientas',
      stat_sigs: 'Firmas WAF',
      stat_llm: 'Proveedores LLM',
      stat_behav: 'Reglas Behavioral',
      stat_sec: 'Capas de Seguridad',
      stat_iface: 'Interfaces',
      feat_title: 'Qu\u00e9 Hace Diferente a TokioAI',
      feat_lead: 'No es otro chatbot. Un agente aut\u00f3nomo que piensa, act\u00faa, observa y aprende. Ejecuci\u00f3n de tools multi-ronda con hasta 10 operaciones consecutivas por mensaje.',
      f1_title: 'Loop de Agente Aut\u00f3nomo',
      f1_body: 'Piensa \u2192 Act\u00faa \u2192 Observa \u2192 Aprende. El agente encadena operaciones multi-paso, maneja errores con reintentos, aprende de fallas para no repetirlas, y pide confirmaci\u00f3n para acciones peligrosas. Hasta 10 rondas de tools por mensaje con timeout de 10 minutos.',
      f2_title: 'Multi-LLM con Auto-Fallback',
      f2_body: 'Soporta Anthropic Claude (Opus 4, Sonnet 4), OpenAI GPT (GPT-4o, o1, o3) y Google Gemini (2.0 Flash, Pro). Fallback autom\u00e1tico entre proveedores asegura cero downtime. Configur\u00e1 tu cadena preferida en .env.',
      f3_title: 'Bot de Telegram \u2014 Multimedia Completo',
      f3_body: 'No solo texto. Procesa im\u00e1genes con Vision API, transcribe mensajes de voz (Gemini + Whisper), analiza documentos (PDF, DOCX, c\u00f3digo), extrae metadata de YouTube, genera y env\u00eda archivos (PDF, CSV, PPTX). Seguridad ACL con comandos admin solo para el owner.',
      f4_title: 'WAF de Producci\u00f3n \u2014 26 Firmas',
      f4_body: 'Motor WAF enterprise con 26 firmas regex detectando SQLi, XSS, RCE, LFI, SSRF, Log4Shell, XXE, SSTI, CRLF, inyecci\u00f3n NoSQL, HTTP smuggling, deserializaci\u00f3n y m\u00e1s. M\u00e1s 7 reglas behavioral para detecci\u00f3n de anomal\u00edas. Bloqueo instant\u00e1neo en primer hit para amenazas cr\u00edticas.',
      f5_title: 'Dashboard SOC Supreme',
      f5_body: 'Feed de ataques SSE en tiempo real, mapa mundial con GeoIP, breakdown OWASP Top 10, visualizaci\u00f3n kill chain, heatmap de ataques (hora x d\u00eda), inteligencia de amenazas con AbuseIPDB, tracking de reputaci\u00f3n IP, monitor de firmas y exportaci\u00f3n CSV. Tema cyberpunk dark con auth JWT.',
      f6_title: 'Deploy GCP con Un Comando',
      f6_body: 'Desplieg\u00e1 todo el stack en Google Cloud con un solo comando en lenguaje natural. Crea VPC, reglas de firewall, IP est\u00e1tica, VM, 7 contenedores Docker, certificados SSL y DNS. Destruilo todo con otro comando. Usa Google Cloud Python SDK directamente.',
      f7_title: '30+ Herramientas',
      f7_body: 'Sistema (bash, python, archivos), Docker, PostgreSQL, GCP compute & WAF, SSH host, IoT & Home Assistant, router OpenWrt, DNS, t\u00faneles, orquestaci\u00f3n de tareas, generaci\u00f3n de documentos y m\u00e1s.',
      f8_title: 'Aprendizaje de Errores y Memoria',
      f8_body: 'Memoria persistente cross-session (SOUL.md + MEMORY.md). El agente recuerda tus preferencias, hechos aprendidos y fallas pasadas. El error learner evita repetir errores. Sistema de plugins para tools custom via workspace/plugins/.',
      f9_title: 'Watchdog y Auto-Reparaci\u00f3n',
      f9_body: 'Monitoreo autom\u00e1tico de salud de todos los contenedores Docker. Detecta servicios ca\u00eddos y los reinicia autom\u00e1ticamente. Registra todos los eventos. Tool de self-heal disponible para recuperaci\u00f3n manual.',
      tools_title: '30+ Tools en 15 Categor\u00edas',
      tools_lead: 'Todas las herramientas que el agente necesita para gestionar infraestructura, seguridad, deploys y operaciones de forma aut\u00f3noma.',
      waf_title: 'Motor WAF & SOC \u2014 En Detalle',
      waf_lead: 'Un pipeline de seguridad de producci\u00f3n que procesa cada request HTTP a trav\u00e9s de m\u00faltiples capas de an\u00e1lisis. 26 firmas, 7 reglas behavioral, detecci\u00f3n de honeypot, reputaci\u00f3n IP y correlaci\u00f3n de ataques multi-fase.',
      waf_s1_title: 'Ingesta de Tr\u00e1fico',
      waf_s1_body: 'Proxy reverso Nginx captura cada request HTTP/HTTPS con rate limiting (general: 10r/s, login: 2r/m, API: 30r/s). Un procesador de logs sigue los access logs en tiempo real y env\u00eda eventos JSON estructurados a Apache Kafka.',
      waf_s2_title: '26 Firmas WAF + 7 Reglas Behavioral',
      waf_s2_body: 'Inyecci\u00f3n (13): SQLi, XSS, Command Injection, XXE, NoSQL, SSTI, CRLF, Log4Shell, LDAP. Control de Acceso (3): Path Traversal/LFI, Detecci\u00f3n de Scanners, WebSocket Hijack. M\u00e1s: SSRF, Fuerza Bruta, HTTP Smuggling, Deserializaci\u00f3n, Cryptominer, API Abuse, Configs Expuestas. Behavioral: Recon, Intentos de Exploit, Requests Malformados, Fuerza Bruta, Ataques Lentos, Exfiltraci\u00f3n de Datos.',
      waf_s3_title: 'Honeypot y Reputaci\u00f3n IP',
      waf_s3_body: 'Endpoints falsos (/wp-admin, /.env, /phpmyadmin) identifican atacantes instant\u00e1neamente (WAF-5001, 0.99 de confianza). Scoring de reputaci\u00f3n IP persistente en PostgreSQL. GeoIP via DB-IP Lite para inteligencia geogr\u00e1fica.',
      waf_s4_title: 'Correlaci\u00f3n de Ataques Multi-Fase',
      waf_s4_body: 'Detecta cadenas de ataque: Recon \u2192 Probe \u2192 Exploit \u2192 Exfiltraci\u00f3n. Agrupa ataques de la misma IP en ventanas de 600s en episodios. La severidad escala autom\u00e1ticamente seg\u00fan cantidad de eventos, tipos y fases. Clasificaci\u00f3n OWASP Top 10 2021 para cada amenaza.',
      waf_s5_title: 'Bloqueo Instant\u00e1neo y Auto-Respuesta',
      waf_s5_body: 'Nivel 1: Bloqueo instant\u00e1neo en firmas cr\u00edticas (confianza \u2265 0.90) \u2014 primer hit, sin espera. Nivel 2: Bloqueo por episodio tras 3+ episodios de ataque. Nivel 3: Bloqueo por rate-limit a 40 req/5min. Blocklist de Nginx actualizado con zero-downtime via sidecar. Bloqueo por 24h por defecto.',
      waf_s6_title: 'Dashboard SOC Supreme',
      waf_s6_body: 'Feed SSE de ataques en tiempo real, mapa mundial, breakdown OWASP, visualizaci\u00f3n kill chain, heatmap de ataques (hora \u00d7 d\u00eda), inteligencia AbuseIPDB, monitor de firmas con conteo de hits, tracking de reputaci\u00f3n IP, export CSV y tema cyberpunk dark. Autenticaci\u00f3n JWT con auditor\u00eda completa en PostgreSQL.',
      arch_title: 'Arquitectura del Sistema',
      arch_lead: 'Dos stacks de deployment trabajando juntos \u2014 el Agente IA y la infraestructura WAF/SOC.',
      arch_1_title: 'Motor del Agente TokioAI',
      arch_1_body: 'Servicio FastAPI con loop de agente async multi-ronda (Piensa \u2192 Act\u00faa \u2192 Observa \u2192 Aprende). Soporte multi-LLM con fallback autom\u00e1tico (Claude, GPT-4, Gemini). 30+ tools, aprendizaje de errores, memoria persistente, seguridad prompt guard y sesiones WebSocket. Interfaces REST API + CLI.',
      arch_2_title: 'Bot de Telegram',
      arch_2_body: 'Interfaz Telegram multimedia completa: texto, im\u00e1genes (Vision API), voz (Gemini + Whisper), documentos (PDF, DOCX, c\u00f3digo), generaci\u00f3n de archivos (PDF, CSV, PPTX), metadata YouTube. Seguridad ACL con comandos admin solo para owner. L\u00f3gica de reintentos para resiliencia de red.',
      arch_3_title: 'PostgreSQL',
      arch_3_body: 'Almacenamiento persistente para memoria de sesiones, datos del workspace, preferencias de usuario, historial de aprendizaje de errores, logs de auditor\u00eda de prompt guard y eventos WAF. Vol\u00famenes para persistencia entre reinicios.',
      int_title: '3 Interfaces, Control Infinito',
      int_lead: 'Control\u00e1 TokioAI desde cualquier lugar: tu terminal, una REST API o Telegram.',
      int_cli_title: 'CLI (Terminal)',
      int_cli_body: 'Terminal interactivo con formato Rich, indicadores de ejecuci\u00f3n de tools en tiempo real, syntax highlighting y salida bonita. Sesiones de conversaci\u00f3n completas.',
      int_api_title: 'REST API + WebSocket',
      int_api_body: 'Servidor FastAPI con endpoints /chat, /health, /stats, /tools, /sessions. WebSocket para sesiones interactivas. Autenticaci\u00f3n por API key y rate limiting.',
      int_tg_title: 'Bot de Telegram',
      int_tg_body: 'Multimedia completo: texto, im\u00e1genes (Vision), voz (Whisper), documentos, generaci\u00f3n de archivos. Soporte YouTube. Seguridad ACL. Admin solo owner: /allow, /deny, /acl.',
      sec_title: 'Arquitectura de Seguridad de 3 Capas',
      sec_lead: 'La seguridad no es una feature \u2014 es la base. Tres capas independientes protegen cada interacci\u00f3n desde el prompt hasta la ejecuci\u00f3n.',
      sec_1_title: 'Prompt Guard',
      sec_1_body: 'WAF para prompts LLM. Detecta ataques de inyecci\u00f3n ANTES de llegar al modelo: intentos de override de rol, extracci\u00f3n de system prompt, inyecci\u00f3n de delimitadores, ataques de encoding (base64/hex) y patrones de abuso de tools. Logging de auditor\u00eda completo.',
      sec_2_title: 'Input Sanitizer',
      sec_2_body: 'Bloquea comandos peligrosos ANTES de la ejecuci\u00f3n: reverse shells (nc -e, bash -i), crypto miners, fork bombs, comandos destructivos (rm -rf /, mkfs, dd), inyecci\u00f3n SQL y path traversal.',
      sec_3_title: 'Canal Seguro',
      sec_3_body: 'Autenticaci\u00f3n por API key (Bearer token / X-API-Key), rate limiting por cliente (60 req/min), ACL de Telegram con comandos admin solo para owner. JWT para dashboard. Cero secretos hardcodeados \u2014 todo desde variables de entorno.',
      sec_4_title: 'Confirmaciones de Acciones',
      sec_4_body: 'Acciones peligrosas requieren confirmaci\u00f3n expl\u00edcita. Defaults conservadores previenen destrucci\u00f3n accidental.',
      sec_5_title: 'Sin Secretos en C\u00f3digo',
      sec_5_body: 'Todos los secretos desde .env. .gitignore completo. Cero credenciales hardcodeadas.',
      sec_6_title: 'Control de Shell',
      sec_6_body: 'HOST_CONTROL_ALLOW_RUN=false por defecto. SSH solo con clave. Todos los comandos remotos requieren confirmaci\u00f3n.',
      gcp_title: 'Deploy GCP \u2014 Un Comando',
      gcp_lead: 'Decile a TokioAI que despliegue y todo se crea autom\u00e1ticamente. Decile que destruya y todo se limpia.',
      gcp_what_title: 'Lo que se Crea',
      gcp_w1: 'Red VPC + Subnet + Reglas de Firewall',
      gcp_w2: 'IP Externa Est\u00e1tica para DNS estable',
      gcp_w3: 'VM Compute Engine (e2-medium) + Ubuntu + Docker',
      gcp_w4: 'SSL via Let\'s Encrypt con renovaci\u00f3n autom\u00e1tica',
      gcp_w5: 'Proxy WAF Nginx con 26 firmas',
      gcp_w6: 'Pipeline Kafka + Zookeeper',
      gcp_w7: 'PostgreSQL con esquema WAF',
      gcp_w8: 'Procesador ML en tiempo real',
      gcp_w9: 'Dashboard SOC con auth JWT',
      gcp_w10: 'Sidecar de blocklist din\u00e1mico',
      gcp_w11: 'Configuraci\u00f3n DNS (API Hostinger)',
      gcp_ops_title: 'Operaciones en Lenguaje Natural',
      qs_title: 'Inicio R\u00e1pido \u2014 3 Pasos',
      qs_lead: 'Funciona en cualquier Linux con Docker. Raspberry Pi, laptop, servidor o VM en la nube.',
      qs_1_title: 'Clonar y Configurar',
      qs_2_title: 'Iniciar el Stack',
      qs_3_title: 'Usar TokioAI',
      qs_deploy_title: '3 Modos de Deploy',
      qs_deploy_body: 'Full Local: Todo en tu m\u00e1quina (dev, testing, Raspberry Pi). H\u00edbrido: Agente local, WAF/Kafka/DB en la nube. Full Cloud: Todo en GCP. M\u00e1xima disponibilidad.',
      tech_title: 'Stack Tecnol\u00f3gico',
      lic_title: 'Open Source (GPLv3)',
      lic_lead: 'TokioAI es libre y open source bajo GNU GPL v3.0.',
      lic_1_title: 'Usar y Modificar',
      lic_1_body: 'Usar, estudiar, modificar y redistribuir libremente para cualquier prop\u00f3sito.',
      lic_2_title: 'Compartir Igual',
      lic_2_body: 'Si distribu\u00eds, compart\u00ed tu c\u00f3digo bajo GPLv3.',
      lic_3_title: 'Como Est\u00e1',
      lic_3_body: 'Provisto sin garant\u00eda. Ver LICENSE para los t\u00e9rminos completos.',
      footer_copy: 'Copyright \u00a9 2026 TokioAI \u2014 GPLv3 \u00b7 Tokio AI Security Research',
    },
  };

  function detectLang() {
    var url = new URL(window.location.href);
    var q = (url.searchParams.get('lang') || '').toLowerCase();
    if (q === 'es' || q === 'en') return q;
    var stored = '';
    try { stored = (localStorage.getItem('tokioai_lang') || '').toLowerCase(); } catch (_) {}
    if (stored === 'es' || stored === 'en') return stored;
    var nav = (navigator.language || 'en').toLowerCase();
    return nav.startsWith('es') ? 'es' : 'en';
  }

  function applyLang(lang) {
    var dict = I18N[lang] || I18N.en;
    document.documentElement.lang = lang;
    currentLang = lang;

    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var key = el.getAttribute('data-i18n');
      if (!key) return;
      var v = dict[key];
      if (typeof v === 'string') el.textContent = v;
    });

    document.querySelectorAll('[data-lang]').forEach(function (btn) {
      var isActive = btn.getAttribute('data-lang') === lang;
      btn.classList.toggle('btn--active', isActive);
      btn.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });

    try { localStorage.setItem('tokioai_lang', lang); } catch (_) {}
  }

  // Language toggles
  document.querySelectorAll('[data-lang]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var lang = btn.getAttribute('data-lang') || 'en';
      applyLang(lang);
    });
  });

  applyLang(detectLang());
})();
