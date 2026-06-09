# Database Setup & Backup Guide

## Overview

The application now uses **SQLite** for persistent data storage instead of in-memory arrays. This allows:
- ✅ Data persistence between sessions
- ✅ Easy backup to git (JSON exports)
- ✅ Seamless sync between devices
- ✅ Local development without external servers

## Database Structure

### Location
- **Database file**: `data/app.db` (created automatically, not in git)
- **Backup file**: `data/app-data.json` (committed to git for sync)
- **Backup history**: `data/backups/app-data-*.json` (local only)

### Tables
- `studios` - Studio information
- `prototypes` - Game prototypes
- `prototype_tests` - Test results (CPI, D1, D3, D7)
- `criteria` - Performance thresholds
- `sprints` - Development sprint plans
- `studio_contracts` - Contract documents & extracted data
- `settings` - Application settings

## Setup Instructions

### 1. First-Time Setup

After cloning the repository:

```bash
# Install dependencies (already done if you have better-sqlite3)
npm install

# Start development server
npm run dev
```

The app will:
1. Create database schema automatically
2. Check for `data/app-data.json` (git-tracked backup)
3. Restore from backup if it exists
4. Or start with fresh database if first clone

### 2. Migration from Old System

If migrating from seed data:

```bash
npm run db:migrate
```

This will:
- Initialize database schema
- Import all seed data from `lib/seed-data.ts`
- Ready for use

## Backup & Sync Workflow

### Manual Backup

Create a backup before pushing to git:

```bash
npm run db:backup
```

This generates:
- Timestamped backup: `data/backups/app-data-2026-05-12T14-30-45-123Z.json`
- Latest backup: `data/app-data.json` (committed to git)

### Automatic Backups via UI

(Coming soon) Dashboard button to trigger backup from UI:
```bash
curl -X POST http://localhost:3000/api/db/backup
```

### Syncing Between Devices

**Device A (making changes):**
1. Make data changes in app
2. Click "Backup Database" button (or run `npm run db:backup`)
3. Commit & push `data/app-data.json` to git

**Device B (pulling changes):**
1. Pull from git (includes updated `data/app-data.json`)
2. Start app: `npm run dev`
3. App automatically detects backup and restores data

**No manual steps needed!** The app checks for `data/app-data.json` on startup and restores if found.

## Git Configuration

The `.gitignore` is set up correctly:

```gitignore
# SQLite files (not synced)
/data/*.db
/data/*.db-shm
/data/*.db-wal
/data/backups/*.json

# But the latest backup IS synced
!/data/app-data.json
```

This means:
- ✅ `data/app-data.json` is tracked in git (safe to push/pull)
- ❌ `data/app.db` is ignored (contains live database, device-specific)
- ❌ `data/backups/` are ignored (local backup history only)

## Common Workflows

### Adding New Data

```typescript
import { dataStore } from '@/lib/data-store';

// Add studio
const studio = dataStore.addStudio({
  id: 'studio-new',
  name: 'New Studio',
  // ...
});

// Changes auto-persist to SQLite
```

### Exporting Full Database

```bash
npm run db:backup
```

Exports to `data/app-data.json` (JSON format, easily readable)

### Restoring from Backup

If something goes wrong:

```bash
npm run db:restore  # Restores from data/app-data.json
```

Or restore from specific backup:

```typescript
import { restoreFromBackup } from '@/lib/db-backup';
restoreFromBackup('./data/backups/app-data-2026-05-12T14-30-45-123Z.json');
```

### Viewing Database Contents

Use any SQLite browser:

```bash
# Open with sqlite3 CLI
sqlite3 data/app.db

# Or use a GUI tool
# - DB Browser for SQLite
# - SQLiteStudio
# - DBeaver
```

Query examples:

```sql
-- View all studios
SELECT * FROM studios;

-- View studio with most prototypes
SELECT s.name, COUNT(p.id) as proto_count
FROM studios s
LEFT JOIN prototypes p ON s.id = p.studio_id
GROUP BY s.id
ORDER BY proto_count DESC;

-- View latest test for each prototype
SELECT p.name, t.platform, t.cpi, t.d1, t.d7, t.tested_at
FROM prototypes p
LEFT JOIN prototype_tests t ON p.id = t.prototype_id
ORDER BY p.name, t.tested_at DESC;
```

## API Endpoints

### Initialize Database
```bash
GET /api/db/init
```
Ensures database is set up and restored from backup.

### Create Backup
```bash
POST /api/db/backup
```
Creates timestamped backup + updates latest backup for git.

Response:
```json
{
  "success": true,
  "message": "Database backed up successfully",
  "backupPath": "data/backups/app-data-2026-05-12T14-30-45-123Z.json"
}
```

## Troubleshooting

### Database locked error
```
Error: database is locked
```
Another process is accessing the database. Make sure:
- Only one dev server is running
- Not editing with SQLite GUI at same time
- No background backups in progress

Solution: Stop all services, delete `data/app.db`, restart

### Backup not showing in git
Check `.gitignore`:
```bash
git check-ignore -v data/app-data.json  # Should show nothing (file is tracked)
git add data/app-data.json --force      # Force add if needed
```

### Data not syncing between devices
1. Ensure backup was created: `data/app-data.json` should exist
2. Check git status: `git status data/app-data.json`
3. Pull on other device: `git pull`
4. Restart app: `npm run dev`

### Restore failed / Backup corrupt
1. Check backup format: `cat data/app-data.json | jq` (should be valid JSON)
2. Try oldest backup: `npm run db:restore -- data/backups/app-data-OLDEST.json`
3. Or re-migrate from seed: `npm run db:migrate`

## Performance Notes

- SQLite queries are synchronous (ok for this app scale)
- Backup operations block briefly (< 1 second for current data)
- Database size: ~50KB for seed data, grows with usage
- Good for 10K+ records before considering migration to PostgreSQL

## Future Improvements

- [ ] Automatic daily backups
- [ ] Conflict resolution for concurrent edits
- [ ] Database migrations system
- [ ] Real-time sync using Replicache or similar
- [ ] Cloud backup to S3 / Google Drive
- [ ] Database version history UI
