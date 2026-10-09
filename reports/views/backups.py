from django.contrib import messages
from django.shortcuts import redirect, render
from django.template.defaultfilters import filesizeformat

from ..services.backup import BACKUP_KEEP, BackupError, backup_dir, backups, make_backup


def backup_list(request):
    """
    Preferences › Backups: the database backups the app made (daily and "Back up now"), and
    "Back up now"
    """
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
    return render(request, 'reports/backup_list.html', {
        'backups': backups(),
        'folder': backup_dir(),
        'keep': BACKUP_KEEP,
    })
