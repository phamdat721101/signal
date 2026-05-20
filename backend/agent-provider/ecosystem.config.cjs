// PM2 process manifest. Runs the HTTP server and the settlement worker as
// separate Node processes so a settle-loop crash cannot break HTTP.
//
// Deploy:
//   pnpm build
//   pm2 startOrReload ecosystem.config.cjs --update-env
//
// Rollback:
//   pm2 stop agent-provider agent-settler
//   (Caddy can be reverted to point /agent-api/* back at Python :8002)

module.exports = {
  apps: [
    {
      name: 'agent-provider',
      script: 'dist/server.js',
      instances: 1,
      exec_mode: 'fork',
      max_restarts: 10,
      min_uptime: '30s',
      restart_delay: 1000,
      max_memory_restart: '512M',
      kill_timeout: 8000, // give SIGTERM 8s to drain in-flight verifies
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      out_file: './logs/agent-provider.out.log',
      error_file: './logs/agent-provider.err.log',
      env: { NODE_ENV: 'production' },
    },
    {
      name: 'agent-settler',
      script: 'dist/settler.js',
      instances: 1,
      exec_mode: 'fork',
      max_restarts: 10,
      min_uptime: '30s',
      restart_delay: 5000,
      max_memory_restart: '256M',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      out_file: './logs/agent-settler.out.log',
      error_file: './logs/agent-settler.err.log',
      env: { NODE_ENV: 'production' },
    },
  ],
};
