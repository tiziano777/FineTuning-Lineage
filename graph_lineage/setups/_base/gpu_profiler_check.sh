#!/bin/bash

echo "================================================================="
echo "        CUDA & PROFILING DIAGNOSTIC SUITE (check_profiler.sh)    "
echo "================================================================="

echo -e "\n[1/4] DIAGNOSTICA AMBIENTE & STRUMENTI DI SISTEMA"
echo "-----------------------------------------------------------------"

echo -e "\n--> [TOOL 1/3] NVIDIA-SMI (Il 'Tachimetro' della GPU)"
echo "    [Utility] Monitora VRAM, temperature e carico istantaneo. Ottimo per prevenire gli Out-Of-Memory (OOM)."
if command -v nvidia-smi &> /dev/null; then
    echo -e "    \e[1;32m[OK]\e[0m Hardware rilevato. Dettagli GPU:"
    nvidia-smi --query-gpu=name,driver_version,compute_cap --format=csv,noheader | sed 's/^/    /'
else
    echo -e "    \e[1;31m[ERRORE]\e[0m nvidia-smi non trovato. Driver non installati correttamente."
fi

echo -e "\n--> [COMPILATORE] NVCC (NVIDIA CUDA Compiler)"
echo "    [Utility] Trasforma i sorgenti C++/CUDA in binari. Necessario per testare i profiler a basso livello."
if command -v nvcc &> /dev/null; then
    echo -e "    \e[1;32m[OK]\e[0m nvcc disponibile:"
    nvcc --version | grep release | sed 's/^/    /'
else
    echo -e "    \e[1;31m[MANCANTE]\e[0m nvcc non trovato nel PATH."
fi

echo -e "\n--> [TOOL 2/3] NCU / Nsight Compute (Il 'Microscopio' del Kernel)"
echo "    [Utility] Isola un singolo Kernel CUDA per vedere se è Memory-Bound o Compute-Bound. Spesso bloccato su Cloud."
if command -v ncu &> /dev/null; then
    echo -e "    \e[1;32m[OK]\e[0m ncu installato:"
    ncu --version | head -n 1 | sed 's/^/    /'
else
    echo -e "    \e[1;33m[ATTENZIONE]\e[0m ncu non trovato (Problema comune su istanze Azure A100)."
fi

echo -e "\n--> [TOOL 3/3] NSYS / Nsight Systems (La 'Scatola Nera' di Sistema)"
echo "    [Utility] Traccia la timeline globale (CPU vs GPU). Identifica se la GPU è ferma ad aspettare i dati dalla CPU."
if command -v nsys &> /dev/null; then
    echo -e "    \e[1;32m[OK]\e[0m nsys installato:"
    nsys --version | head -n 1 | sed 's/^/    /'
else
    echo -e "    \e[1;31m[MANCANTE]\e[0m nsys non trovato."
fi

echo -e "\n--> [AMBIENTE] PYTORCH INTERFACE"
echo "    [Utility] Verifica che CUDA sia correttamente esposta a Python per l'addestramento LLM (Unsloth/DPO)."
if command -v python3 &> /dev/null && python3 -c "import torch" &> /dev/null; then
    echo -e "    \e[1;32m[OK]\e[0m PyTorch configurato con successo:"
    python3 -c "import torch; print(f'    Versione: {torch.__version__} | CUDA Rilevata: {torch.cuda.is_available()} | Modello GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"None\"}')"
else
    echo -e "    \e[1;33m[ATTENZIONE]\e[0m PyTorch non installato o CUDA non mappata nell'ambiente Python attivo."
fi


echo -e "\n[2/4] COMPILAZIONE CODICE DI TEST (WORKLOAD FORZATO)"
echo "-----------------------------------------------------------------"
echo "--> Scrittura del file /tmp/check_heavy_work.cu..."
echo "    [Info] Generiamo un workload pesante con funzioni trigonometriche e copie esplicite (Host<->Device)."
echo "    Questo impedisce al compilatore di ottimizzare o rimuovere il kernel, forzando la GPU a lavorare."

cat > /tmp/check_heavy_work.cu << 'EOF'
#include <cuda_runtime.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>

#define N 1000000
#define ITERATIONS 100

__global__ void heavy_compute(float *a, float *b, float *c, int n) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < n) {
        float sum = 0.0f;
        for (int j = 0; j < ITERATIONS; j++) {
            sum += a[idx] * b[idx] + sinf(a[idx] * j) * cosf(b[idx] * j);
        }
        c[idx] = sum / ITERATIONS;
    }
}

int main() {
    float *d_a, *d_b, *d_c;
    float *h_a, *h_b, *h_c;
    int size = N * sizeof(float);
    
    h_a = (float*)malloc(size);
    h_b = (float*)malloc(size);
    h_c = (float*)malloc(size);
    
    for (int i = 0; i < N; i++) {
        h_a[i] = (float)i / N;
        h_b[i] = 1.0f - (float)i / N;
    }
    
    cudaMalloc(&d_a, size);
    cudaMalloc(&d_b, size);
    cudaMalloc(&d_c, size);
    
    cudaMemcpy(d_a, h_a, size, cudaMemcpyHostToDevice);
    cudaMemcpy(d_b, h_b, size, cudaMemcpyHostToDevice);
    
    int threads = 256;
    int blocks = (N + threads - 1) / threads;
    
    heavy_compute<<<blocks, threads>>>(d_a, d_b, d_c, N);
    cudaDeviceSynchronize();
    
    cudaMemcpy(h_c, d_c, size, cudaMemcpyDeviceToHost);
    
    cudaFree(d_a);
    cudaFree(d_b);
    cudaFree(d_c);
    free(h_a);
    free(h_b);
    free(h_c);
    return 0;
}
EOF

if command -v nvcc &> /dev/null; then
    nvcc -g -O0 -lineinfo /tmp/check_heavy_work.cu -o /tmp/check_heavy_work 2>/dev/null
    if [ $? -eq 0 ]; then
        echo -e "    \e[1;32m[OK]\e[0m Binario generato correttamente in: /tmp/check_heavy_work"
    else
        echo -e "    \e[1;31m[ERRORE]\e[0m Compilazione fallita."
    fi
else
    echo "    [SKIP] Compilazione saltata: nvcc non disponibile."
fi


echo -e "\n[3/4] DIAGNOSI FUNZIONALE DEI PROFILER (CHI FUNZIONA E CHI È BLOCCATO?)"
echo "-----------------------------------------------------------------"

if [ -f /tmp/check_heavy_work ]; then
    if command -v ncu &> /dev/null; then
        echo "--> Esecuzione Test NCU..."
        echo "    [Diagnosi] Se vedi 'WARNING== No kernels were profiled', significa che i contatori hardware"
        echo "    della GPU sono sotto chiave (comune su Azure). Sarà necessario usare i flag di override o passare a NSYS."
        ncu_test=$(ncu --target-processes all /tmp/check_heavy_work 2>&1)
        if echo "$ncu_test" | grep -q "WARNING== No kernels were profiled"; then
            echo -e "    RISULTATO: \e[1;31mNCU BLOCCATO\e[0m (I driver cloud vietano l'accesso microscopico al kernel)."
        else
            echo -e "    RISULTATO: \e[1;32mNCU FUNZIONANTE\e[0m (Riesci ad analizzare i dettagli hardware)."
        fi
    fi

    if command -v nsys &> /dev/null; then
        echo "--> Esecuzione Test NSYS..."
        echo "    [Diagnosi] NSYS lavora a più alto livello. Dovrebbe catturare i tempi macro (cudaLaunchKernel)"
        echo "    e i trasferimenti di memoria anche quando NCU fallisce."
        nsys profile --trace=cuda,nvtx --stats=true --force-overwrite=true -o /tmp/nsys_check_test /tmp/check_heavy_work &> /tmp/nsys_debug.log
        if grep -q "SKIPPED:.*does not contain CUDA kernel data" /tmp/nsys_debug.log; then
            echo -e "    RISULTATO: \e[1;33mNSYS PARZIALE\e[0m (Esegue il tracciamento di sistema ma omette i dettagli interni del kernel)."
        else
            echo -e "    RISULTATO: \e[1;32mNSYS FUNZIONANTE\e[0m (Report generato con successo in /tmp/nsys_check_test.nsys-rep)."
        fi
    fi
else
    echo "    [SKIP] Test profiler saltati: binario di test non compilato."
fi

if python3 -c "import torch" &> /dev/null && python3 -c "import torch; exit(0 if torch.cuda.is_available() else 1)" &> /dev/null; then
    echo "--> Esecuzione Test PyTorch Profiler..."
    echo "    [Diagnosi] Lo strumento perfetto per DPO/Unsloth. Traduce i dati di basso livello direttamente nelle"
    echo "    funzioni Python che utilizzi nel codice (es. identificando se il collo di bottiglia è il Backward Pass)."
    cat > /tmp/check_pytorch_prof.py << 'EOF'
import torch
import torch.profiler
device = torch.device('cuda')
x = torch.randn(2048, 2048, device=device)
w = torch.randn(2048, 2048, device=device)
with torch.profiler.profile(
    activities=[torch.profiler.ProfilerActivity.CUDA],
    record_shapes=True,
    profile_memory=True
) as prof:
    for _ in range(5):
        x = torch.matmul(x, w)
        torch.cuda.synchronize()
print("    RISULTATO: \033[1;32mPYTORCH PROFILER FUNZIONANTE\033[0m (Rilevamento metriche core superato)")
print(prof.key_averages().table(sort_by="cuda_time_total", row_limit=3))
EOF
    python3 /tmp/check_pytorch_prof.py
else
    echo "--> Test PyTorch Profiler..."
    echo -e "    RISULTATO: \e[1;31mSALTATO\e[0m (PyTorch non disponibile o CUDA non agganciata a Python)."
fi


echo -e "\n[4/4] COMANDI PRONTI ALL'USO PER IL TUO SCRIPT DPO / UNSLOTH"
echo "-----------------------------------------------------------------"
echo "In base allo stato emerso, ecco le migliori opzioni per profilare il tuo codice reale:"
echo ""
echo "1) Profiling Completo Timeline di Sistema (Consigliato per blocchi CPU/GPU e macro-ottimizzazioni):"
echo "   nsys profile --trace=cuda,nvtx,osrt --cuda-memory-usage=true --stats=true -o dpo_report python3 tuo_script.py"
echo ""
echo "2) Analisi di Basso Livello (Se NCU è risultato funzionante, per dettagli su singoli layer custom):"
echo "   ncu --target-processes all --set full -o ncu_dpo_report python3 tuo_script.py"
echo ""
echo "3) Monitoraggio Istantaneo e leggero in background (Da tenere aperto in un terminale separato):"
echo "   watch -n 0.5 nvidia-smi"
echo "================================================================="