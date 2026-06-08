// PM2 process manifest — single agent-provider app (Arbitrum Sepolia x402).
//
// Deploy:
//   npm run build
//   pm2 startOrReload ecosystem.config.cjs --update-env
//
// All runtime config is read from the local `.env` file (loaded by the
// service code via dotenv). This avoids hardcoding host/port/pathPrefix
// values that differ between local dev and the VPS reverse-proxy mount.

module.exports = {
  apps: [
    {
      name: 'agent-provider',
      script: 'dist/src/server.js',
      instances: 1,
      exec_mode: 'fork',
      max_restarts: 10,
      min_uptime: '30s',
      restart_delay: 1000,
      max_memory_restart: '512M',
      kill_timeout: 8000,
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      out_file: './logs/agent-provider.out.log',
      error_file: './logs/agent-provider.err.log',
      env: { NODE_ENV: 'production' },
    },
  ],
};
