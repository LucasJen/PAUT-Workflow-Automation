from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from .models import Scope, Probe, CalibrationBlock, SensitivityBlock, Encoder
from .forms import ScopeForm, ProbeForm, CalibrationBlockForm, SensitivityBlockForm, EncoderForm


# ── Scopes ──────────────────────────────────────────────────────────────────

def scope_list(request):
    scopes = Scope.objects.all()
    if request.method == 'POST':
        selected_pks = request.POST.getlist('selected')
        if 'delete' in request.POST:
            Scope.objects.filter(pk__in=selected_pks).delete()
            return redirect('scope-list')
        if 'edit' in request.POST and len(selected_pks) == 1:
            return redirect('edit-scope', pk=selected_pks[0])
        if 'duplicate' in request.POST and len(selected_pks) == 1:
            original = get_object_or_404(Scope, pk=selected_pks[0])
            original.pk = None
            original.save()
            return redirect('scope-list')
    return render(request, 'equipment/scope_list.html', {'items': scopes})


def new_scope(request):
    """The edit page for a Scope not saved yet: saving creates it (just opening the page doesn't)."""
    return edit_scope(request)


def edit_scope(request, pk=None):
    scope = get_object_or_404(Scope, pk=pk) if pk is not None else Scope()
    if request.method == 'POST':
        if 'delete' in request.POST:
            if scope.pk is None:
                return redirect('scope-list')
            scope.delete()
            messages.success(request, 'Scope deleted.')
            return redirect('scope-list')
        form = ScopeForm(request.POST, instance=scope)
        if form.is_valid():
            form.save()
            messages.success(request, 'Scope saved.')
            return redirect('scope-list')
    else:
        form = ScopeForm(instance=scope)
    return render(request, 'equipment/edit_scope.html', {'form': form, 'scope': scope})


# ── Probes ───────────────────────────────────────────────────────────────────

def probe_list(request):
    probes = Probe.objects.all()
    if request.method == 'POST':
        selected_pks = request.POST.getlist('selected')
        if 'delete' in request.POST:
            Probe.objects.filter(pk__in=selected_pks).delete()
            return redirect('probe-list')
        if 'edit' in request.POST and len(selected_pks) == 1:
            return redirect('edit-probe', pk=selected_pks[0])
        if 'duplicate' in request.POST and len(selected_pks) == 1:
            original = get_object_or_404(Probe, pk=selected_pks[0])
            original.pk = None
            original.save()
            return redirect('probe-list')
    return render(request, 'equipment/probe_list.html', {'items': probes})


def new_probe(request):
    """The edit page for a Probe not saved yet: saving creates it (just opening the page doesn't)."""
    return edit_probe(request)


def edit_probe(request, pk=None):
    probe = get_object_or_404(Probe, pk=pk) if pk is not None else Probe()
    if request.method == 'POST':
        if 'delete' in request.POST:
            if probe.pk is None:
                return redirect('probe-list')
            probe.delete()
            messages.success(request, 'Probe deleted.')
            return redirect('probe-list')
        form = ProbeForm(request.POST, instance=probe)
        if form.is_valid():
            form.save()
            messages.success(request, 'Probe saved.')
            return redirect('probe-list')
    else:
        form = ProbeForm(instance=probe)
    return render(request, 'equipment/edit_probe.html', {'form': form, 'probe': probe})


# ── Calibration Blocks ───────────────────────────────────────────────────────

def cal_block_list(request):
    cal_blocks = CalibrationBlock.objects.all()
    if request.method == 'POST':
        selected_pks = request.POST.getlist('selected')
        if 'delete' in request.POST:
            CalibrationBlock.objects.filter(pk__in=selected_pks).delete()
            return redirect('cal-block-list')
        if 'edit' in request.POST and len(selected_pks) == 1:
            return redirect('edit-cal-block', pk=selected_pks[0])
        if 'duplicate' in request.POST and len(selected_pks) == 1:
            original = get_object_or_404(CalibrationBlock, pk=selected_pks[0])
            original.pk = None
            original.save()
            return redirect('cal-block-list')
    return render(request, 'equipment/cal_block_list.html', {'items': cal_blocks})


def new_cal_block(request):
    """The edit page for a CalibrationBlock not saved yet: saving creates it (just opening the page doesn't)."""
    return edit_cal_block(request)


def edit_cal_block(request, pk=None):
    cal_block = get_object_or_404(CalibrationBlock, pk=pk) if pk is not None else CalibrationBlock()
    if request.method == 'POST':
        if 'delete' in request.POST:
            if cal_block.pk is None:
                return redirect('cal-block-list')
            cal_block.delete()
            messages.success(request, 'Calibration block deleted.')
            return redirect('cal-block-list')
        form = CalibrationBlockForm(request.POST, instance=cal_block)
        if form.is_valid():
            form.save()
            messages.success(request, 'Calibration block saved.')
            return redirect('cal-block-list')
    else:
        form = CalibrationBlockForm(instance=cal_block)
    return render(request, 'equipment/edit_cal_block.html', {'form': form, 'cal_block': cal_block})


# ── Sensitivity Blocks ───────────────────────────────────────────────────────

def sensitivity_block_list(request):
    sensitivity_blocks = SensitivityBlock.objects.all()
    if request.method == 'POST':
        selected_pks = request.POST.getlist('selected')
        if 'delete' in request.POST:
            SensitivityBlock.objects.filter(pk__in=selected_pks).delete()
            return redirect('sensitivity-block-list')
        if 'edit' in request.POST and len(selected_pks) == 1:
            return redirect('edit-sensitivity-block', pk=selected_pks[0])
        if 'duplicate' in request.POST and len(selected_pks) == 1:
            original = get_object_or_404(SensitivityBlock, pk=selected_pks[0])
            original.pk = None
            original.save()
            return redirect('sensitivity-block-list')
    return render(request, 'equipment/sensitivity_block_list.html', {'items': sensitivity_blocks})


def new_sensitivity_block(request):
    """The edit page for a SensitivityBlock not saved yet: saving creates it (just opening the page doesn't)."""
    return edit_sensitivity_block(request)


def edit_sensitivity_block(request, pk=None):
    block = get_object_or_404(SensitivityBlock, pk=pk) if pk is not None else SensitivityBlock()
    if request.method == 'POST':
        if 'delete' in request.POST:
            if block.pk is None:
                return redirect('sensitivity-block-list')
            block.delete()
            messages.success(request, 'Sensitivity block deleted.')
            return redirect('sensitivity-block-list')
        form = SensitivityBlockForm(request.POST, instance=block)
        if form.is_valid():
            form.save()
            messages.success(request, 'Sensitivity block saved.')
            return redirect('sensitivity-block-list')
    else:
        form = SensitivityBlockForm(instance=block)
    return render(request, 'equipment/edit_sensitivity_block.html', {'form': form, 'block': block})


# ── Encoders ─────────────────────────────────────────────────────────────────

def encoder_list(request):
    encoders = Encoder.objects.all()
    if request.method == 'POST':
        selected_pks = request.POST.getlist('selected')
        if 'delete' in request.POST:
            Encoder.objects.filter(pk__in=selected_pks).delete()
            return redirect('encoder-list')
        if 'edit' in request.POST and len(selected_pks) == 1:
            return redirect('edit-encoder', pk=selected_pks[0])
        if 'duplicate' in request.POST and len(selected_pks) == 1:
            original = get_object_or_404(Encoder, pk=selected_pks[0])
            original.pk = None
            original.save()
            return redirect('encoder-list')
    return render(request, 'equipment/encoder_list.html', {'items': encoders})


def new_encoder(request):
    """The edit page for a Encoder not saved yet: saving creates it (just opening the page doesn't)."""
    return edit_encoder(request)


def edit_encoder(request, pk=None):
    encoder = get_object_or_404(Encoder, pk=pk) if pk is not None else Encoder()
    if request.method == 'POST':
        if 'delete' in request.POST:
            if encoder.pk is None:
                return redirect('encoder-list')
            encoder.delete()
            messages.success(request, 'Encoder deleted.')
            return redirect('encoder-list')
        form = EncoderForm(request.POST, instance=encoder)
        if form.is_valid():
            form.save()
            messages.success(request, 'Encoder saved.')
            return redirect('encoder-list')
    else:
        form = EncoderForm(instance=encoder)
    return render(request, 'equipment/edit_encoder.html', {'form': form, 'encoder': encoder})
