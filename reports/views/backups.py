from django.contrib import messages
from django.shortcuts import redirect, render
from django.template.defaultfilters import filesizeformat

from ..services.backup import BACKUP_KEEP, BackupError, backup_dir, backups, make_backup
from ..services.media_cleanup import delete_unused, unused_files


def backup_list(request):
    """
    Preferences › Backups: the database backups the app made (daily and "Back up now"), "Back up
    now", and the unused files in media/ (deleted on request, after a backup that keeps a copy)
    """
    if request.method == 'POST' and 'delete_unused' in request.POST:
        try:
            made = make_backup()   # its media mirror keeps a copy of every file deleted below
        except BackupError as e:
            messages.error(request, f'{e} No files were deleted.')
            return redirect('backup-list')
        count, size = delete_unused()
        messages.success(request, f"Deleted {count} unused file{'s' if count != 1 else ''} ({filesizeformat(size)}). "
                                  f"A copy of each is in the backup's media folder ({made['name']}).")
        return redirect('backup-list')
    if request.method == 'POST' and 'backup' in request.POST:
        try:
            made = make_backup()
        except BackupError as e:
            messages.error(request, str(e))
        else:
            files = made['media_copied']
            messages.success(request, f"Backed up to {made['name']} ({filesizeformat(made['size'])})"
                                      + (f", and {files} new file{'s' if files != 1 else ''} copied from media." if files else '.'))
        return redirect('backup-list')
    unused = unused_files()
    return render(request, 'reports/backup_list.html', {
        'backups': backups(),
        'folder': backup_dir(),
        'keep': BACKUP_KEEP,
        'unused': unused,
        'unused_size': sum(f['size'] for f in unused),
    })
