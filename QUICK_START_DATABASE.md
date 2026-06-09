# Database Quick Start Guide

## What's Been Set Up

Your app now has a complete **SQLite database infrastructure** ready for use:

✅ **Database files** - Located in `data/` directory
✅ **Backup system** - JSON backups for git tracking  
✅ **API endpoints** - Server-side database operations
✅ **Auto-restore** - Automatic recovery from backups on startup
✅ **Git integration** - Latest backup (`data/app-data.json`) tracked in git

## Current State

- **App runs normally** with in-memory seed data
- **Database is ready** for full integration
- **Backup system works** - ready to persist changes between devices

## Using the Database

### 1. Create a Backup (Before Syncing)

```bash
curl -X POST http://localhost:3000/api/db/backup
```

Or from terminal:
```bash
npm run db:backup
```

This creates:
- `data/backups/app-data-TIMESTAMP.json` (local history)
- `data/app-data.json` (synced to git)

### 2. Push to Git

```bash
git add data/app-data.json
git commit -m "chore: backup database"
git push
```

### 3. Pull on Another Device

```bash
git pull  # Includes updated data/app-data.json
npm run dev  # App auto-restores from backup!
```

## Migration Path (When Ready)

To fully integrate the database (make data changes persistent):

1. Update `lib/data-store.ts` to use `lib/api-client.ts` instead of seed data
2. All server operations in `lib/db-utils.ts` are ready to use
3. API endpoints handle all database CRUD operations

Example migration for one operation:

```typescript
// Before (in-memory):
const studios = SEED_STUDIOS;

// After (database):
const studios = await api.getAllStudios();
```

## Database Files Overview

```
data/
├── app.db              # ← SQLite database (not in git, local only)
├── app.db-shm         # ← SQLite temp file (ignored)
├── app.db-wal         # ← SQLite temp file (ignored)
├── app-data.json      # ← Latest backup (✓ in git, syncs between devices)
└── backups/
    ├── app-data-2026-05-12T...json
    ├── app-data-2026-05-11T...json
    └── ...             # Old backups (local only, not in git)
```

## Making Data Changes Persist

When you want changes (new studios, updated prototypes, etc) to sync across devices:

1. Make the change in the app
2. Manually backup: `POST /api/db/backup`
3. Git commit & push
4. Pull on other device - data auto-restored!

## Troubleshooting

**Q: How do I know if the database is working?**
A: Check `data/app.db` exists (it will be created on first run)

**Q: How do I reset to seed data?**
A: Delete `data/app.db` and `data/app-data.json`, restart app

**Q: Backup is stuck?**
A: Check if dev server is running and accessible

**Q: Data not syncing between devices?**
A: Ensure `data/app-data.json` is committed and pushed to git

## See Also

- [Full Database Documentation](./DATABASE.md)
- [Database Schema](./lib/db.ts)
- [API Endpoints](./app/api/)
