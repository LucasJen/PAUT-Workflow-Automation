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
    return render(request, 'equipment/scope_list.html', {'scopes': scopes})


def new_scope(request):
    scope = Scope.objects.create()
    return redirect('edit-scope', pk=scope.pk)


def edit_scope(request, pk):
    scope = get_object_or_404(Scope, pk=pk)
    if request.method == 'POST':
        if 'delete' in request.POST:
            scope.delete()
            return redirect('scope-list')
        form = ScopeForm(request.POST, instance=scope)
        if form.is_valid():
            form.save()
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
    return render(request, 'equipment/probe_list.html', {'probes': probes})


def new_probe(request):
    probe = Probe.objects.create()
    return redirect('edit-probe', pk=probe.pk)


def edit_probe(request, pk):
    probe = get_object_or_404(Probe, pk=pk)
    if request.method == 'POST':
        if 'delete' in request.POST:
            probe.delete()
            return redirect('probe-list')
        form = ProbeForm(request.POST, instance=probe)
        if form.is_valid():
            form.save()
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
    return render(request, 'equipment/cal_block_list.html', {'cal_blocks': cal_blocks})


def new_cal_block(request):
    cal_block = CalibrationBlock.objects.create()
    return redirect('edit-cal-block', pk=cal_block.pk)


def edit_cal_block(request, pk):
    cal_block = get_object_or_404(CalibrationBlock, pk=pk)
    if request.method == 'POST':
        if 'delete' in request.POST:
            cal_block.delete()
            return redirect('cal-block-list')
        form = CalibrationBlockForm(request.POST, instance=cal_block)
        if form.is_valid():
            form.save()
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
    return render(request, 'equipment/sensitivity_block_list.html', {'sensitivity_blocks': sensitivity_blocks})


def new_sensitivity_block(request):
    block = SensitivityBlock.objects.create()
    return redirect('edit-sensitivity-block', pk=block.pk)


def edit_sensitivity_block(request, pk):
    block = get_object_or_404(SensitivityBlock, pk=pk)
    if request.method == 'POST':
        if 'delete' in request.POST:
            block.delete()
            return redirect('sensitivity-block-list')
        form = SensitivityBlockForm(request.POST, instance=block)
        if form.is_valid():
            form.save()
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
    return render(request, 'equipment/encoder_list.html', {'encoders': encoders})


def new_encoder(request):
    encoder = Encoder.objects.create()
    return redirect('edit-encoder', pk=encoder.pk)


def edit_encoder(request, pk):
    encoder = get_object_or_404(Encoder, pk=pk)
    if request.method == 'POST':
        if 'delete' in request.POST:
            encoder.delete()
            return redirect('encoder-list')
        form = EncoderForm(request.POST, instance=encoder)
        if form.is_valid():
            form.save()
            return redirect('encoder-list')
    else:
        form = EncoderForm(instance=encoder)
    return render(request, 'equipment/edit_encoder.html', {'form': form, 'encoder': encoder})
