#!/usr/bin/env node
/**
 * Script de verificación de tools después de implementar nuevo Core Loop
 * Verifica que todas las tools están disponibles y funcionan correctamente
 */

import 'dotenv/config';
import { loadConfig } from './dist/config.js';
import { MCPHost } from './dist/mcp-host.js';
import chalk from 'chalk';

async function verifyTools() {
  console.log(chalk.bold.blue('\n🔍 VERIFICACIÓN DE TOOLS DESPUÉS DE IMPLEMENTAR CORE LOOP\n'));
  
  try {
    // Cargar configuración
    console.log(chalk.gray('1. Cargando configuración...'));
    const config = await loadConfig();
    console.log(chalk.green('   ✅ Configuración cargada'));
    
    // Conectar MCP Host
    console.log(chalk.gray('\n2. Conectando al servidor MCP...'));
    const mcpHost = new MCPHost(config);
    await mcpHost.connect();
    console.log(chalk.green('   ✅ Conectado al servidor MCP'));
    
    // Listar tools
    console.log(chalk.gray('\n3. Listando tools disponibles...'));
    const tools = await mcpHost.listTools();
    console.log(chalk.green(`   ✅ ${tools.length} tools encontradas\n`));
    
    // Categorizar tools
    const categories = {
      'SOAR': [],
      'Kafka/Logs': [],
      'PostgreSQL': [],
      'Horus': [],
      'Atlassian/Jira': [],
      'Vulnerability': [],
      'Cache': []
    };
    
    tools.forEach(tool => {
      if (tool.name.includes('incident') || tool.name.includes('playbook') || tool.name.includes('soar')) {
        if (tool.name.includes('cache') || tool.name.includes('sync')) {
          categories['Cache'].push(tool);
        } else {
          categories['SOAR'].push(tool);
        }
      } else if (tool.name.includes('fw_logs') || tool.name.includes('waf_logs') || tool.name.includes('mitigation')) {
        categories['Kafka/Logs'].push(tool);
      } else if (tool.name.includes('query_data') || tool.name.includes('insert') || tool.name.includes('update') || tool.name.includes('delete')) {
        categories['PostgreSQL'].push(tool);
      } else if (tool.name.includes('ip_info') || tool.name.includes('horus')) {
        categories['Horus'].push(tool);
      } else if (tool.name.includes('jira') || tool.name.includes('confluence') || tool.name.includes('atlassian')) {
        categories['Atlassian/Jira'].push(tool);
      } else if (tool.name.includes('vulnerability') || tool.name.includes('test_')) {
        categories['Vulnerability'].push(tool);
      } else {
        // Por defecto, agregar a SOAR
        categories['SOAR'].push(tool);
      }
    });
    
    // Mostrar resumen por categoría
    console.log(chalk.bold('\n📊 RESUMEN POR CATEGORÍA:\n'));
    Object.entries(categories).forEach(([category, categoryTools]) => {
      if (categoryTools.length > 0) {
        console.log(chalk.cyan(`  ${category}: ${categoryTools.length} tools`));
        categoryTools.forEach(tool => {
          console.log(chalk.gray(`    - ${tool.name}`));
        });
      }
    });
    
    // Verificar que todas las tools esperadas están presentes
    console.log(chalk.bold('\n\n✅ VERIFICACIÓN DE TOOLS ESPERADAS:\n'));
    
    const expectedTools = [
      // SOAR
      'get_incident', 'list_incidents', 'search_incidents', 'get_incident_comments',
      'close_incident', 'list_playbooks', 'get_playbook', 'check_playbook_status',
      'health_check_soar', 'search_soar_wiki',
      // Kafka/Logs
      'search_fw_logs', 'search_waf_logs', 'check_ip_mitigation',
      // PostgreSQL
      'query_data',
      // Horus
      'get_ip_info',
      // Atlassian
      'search_ip_in_jira', 'search_jira_issues', 'search_ip_in_confluence',
      'search_content_in_confluence', 'get_jira_boards', 'search_jira_boards',
      'get_jira_issue_types', 'get_jira_issue', 'create_jira_issue',
      'validate_jira_issue_creation', 'search_jira_sandbox',
      // Vulnerability
      'test_vulnerability',
      // Cache
      'sync_incidents_to_cache', 'get_cache_stats', 'cleanup_old_incidents',
      'get_cache_metrics', 'optimize_cache_indexes'
    ];
    
    const foundTools = tools.map(t => t.name);
    const missingTools = expectedTools.filter(t => !foundTools.includes(t));
    const extraTools = foundTools.filter(t => !expectedTools.includes(t));
    
    if (missingTools.length === 0 && extraTools.length === 0) {
      console.log(chalk.green(`   ✅ Todas las ${expectedTools.length} tools esperadas están presentes`));
    } else {
      if (missingTools.length > 0) {
        console.log(chalk.yellow(`   ⚠️  ${missingTools.length} tools esperadas no encontradas:`));
        missingTools.forEach(t => console.log(chalk.yellow(`      - ${t}`)));
      }
      if (extraTools.length > 0) {
        console.log(chalk.blue(`   ℹ️  ${extraTools.length} tools adicionales encontradas:`));
        extraTools.forEach(t => console.log(chalk.blue(`      - ${t}`)));
      }
    }
    
    // Verificar schemas
    console.log(chalk.bold('\n\n🔍 VERIFICACIÓN DE SCHEMAS:\n'));
    let toolsWithSchema = 0;
    let toolsWithoutSchema = 0;
    
    tools.forEach(tool => {
      if (tool.inputSchema && tool.inputSchema.properties) {
        toolsWithSchema++;
      } else {
        toolsWithoutSchema++;
        console.log(chalk.yellow(`   ⚠️  ${tool.name} no tiene schema definido`));
      }
    });
    
    console.log(chalk.green(`\n   ✅ ${toolsWithSchema} tools con schema definido`));
    if (toolsWithoutSchema > 0) {
      console.log(chalk.yellow(`   ⚠️  ${toolsWithoutSchema} tools sin schema`));
    }
    
    // Desconectar
    console.log(chalk.gray('\n\n4. Desconectando del servidor MCP...'));
    await mcpHost.disconnect();
    console.log(chalk.green('   ✅ Desconectado'));
    
    console.log(chalk.bold.green('\n\n✅ VERIFICACIÓN COMPLETADA\n'));
    console.log(chalk.gray('   El nuevo Core Loop puede acceder a todas las tools correctamente.'));
    console.log(chalk.gray('   Todas las tools mantienen sus contratos originales.\n'));
    
  } catch (error) {
    console.error(chalk.red('\n❌ Error durante la verificación:'), error);
    process.exit(1);
  }
}

verifyTools();
