
<script>
let strNombreUsuario = '{{ session.get("user_nombre", "Loreidy") }}';
async function enviarMensajeAstrid() {
    const input = document.getElementById('astrid-input');
    const msg = input.value.trim();
    if(!msg) return;
    input.value = '';
    
    const chatContainer = document.getElementById('astrid-chat-container');
    chatContainer.innerHTML += `<div class="flex items-start gap-3 justify-end"><div class="bg-indigo-50 border border-indigo-100 rounded-2xl rounded-tr-none px-4 py-3 text-sm text-slate-700 shadow-sm max-w-[80%]">${msg}</div><div class="w-8 h-8 rounded-full bg-slate-200 flex-shrink-0 flex items-center justify-center text-slate-600 text-xs"><i class="bi bi-person-fill"></i></div></div>`;
    chatContainer.scrollTop = chatContainer.scrollHeight;

    // Loading bubble
    const loaderId = 'loader-' + Date.now();
    chatContainer.innerHTML += `<div id="${loaderId}" class="flex items-start gap-3"><div class="w-8 h-8 rounded-full bg-indigo-500 flex-shrink-0 flex items-center justify-center text-white text-xs"><i class="bi bi-robot"></i></div><div class="bg-white border border-slate-200 rounded-2xl rounded-tl-none px-4 py-3 text-sm text-slate-400 shadow-sm max-w-[80%] flex gap-1"><span class="animate-bounce">.</span><span class="animate-bounce delay-75">.</span><span class="animate-bounce delay-150">.</span></div></div>`;
    chatContainer.scrollTop = chatContainer.scrollHeight;

    try {
        const res = await fetch('/api/astrid', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({prompt: msg})
        });
        const data = await res.json();
        document.getElementById(loaderId).remove();
        
        if(data.success) {
            chatContainer.innerHTML += `<div class="flex items-start gap-3"><div class="w-8 h-8 rounded-full bg-indigo-500 flex-shrink-0 flex items-center justify-center text-white text-xs"><i class="bi bi-robot"></i></div><div class="bg-white border border-slate-200 rounded-2xl rounded-tl-none px-4 py-3 text-sm text-slate-700 shadow-sm max-w-[80%]">${data.respuesta.replace(/\n/g, '<br>')}</div></div>`;
            hablarAstrid(data.respuesta);
        } else {
            chatContainer.innerHTML += `<div class="flex items-start gap-3"><div class="w-8 h-8 rounded-full bg-rose-500 flex-shrink-0 flex items-center justify-center text-white text-xs"><i class="bi bi-exclamation-triangle"></i></div><div class="bg-rose-50 border border-rose-200 rounded-2xl rounded-tl-none px-4 py-3 text-sm text-rose-700 shadow-sm max-w-[80%]">Error: ${data.error}</div></div>`;
        }
    } catch(e) {
        if(document.getElementById(loaderId)) document.getElementById(loaderId).remove();
        chatContainer.innerHTML += `<div class="flex items-start gap-3"><div class="w-8 h-8 rounded-full bg-rose-500 flex-shrink-0 flex items-center justify-center text-white text-xs"><i class="bi bi-exclamation-triangle"></i></div><div class="bg-rose-50 border border-rose-200 rounded-2xl rounded-tl-none px-4 py-3 text-sm text-rose-700 shadow-sm max-w-[80%]">Fallo de conexión con Astrid.</div></div>`;
    }
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

function hablarAstrid(texto) {
    if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(texto);
        utterance.lang = 'es-VE';
        // Remove markdown or special characters before speaking
        utterance.text = texto.replace(/[*#]/g, '');
        window.speechSynthesis.speak(utterance);
    }
}

function iniciarDictadoAstrid() {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
        Swal.fire('No soportado', 'Tu navegador no soporta dictado por voz.', 'info');
        return;
    }
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    recognition.lang = 'es-VE';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    
    const btn = document.getElementById('btn-astrid-mic');
    btn.classList.add('bg-rose-100', 'text-rose-600', 'animate-pulse');
    
    recognition.onresult = function(event) {
        const result = event.results[0][0].transcript;
        document.getElementById('astrid-input').value = result;
        enviarMensajeAstrid();
    };
    recognition.onend = function() {
        btn.classList.remove('bg-rose-100', 'text-rose-600', 'animate-pulse');
    };
    recognition.start();
}
</script>

<script>
async function cargarPerfilProveedor(rif) {
    switchTab('perfil-proveedor');
    document.getElementById('perfil_prov_nombre').innerText = 'Cargando...';
    document.getElementById('perfil_prov_rif').innerText = rif;
    document.getElementById('bodyPerfilOrdenes').innerHTML = '<tr><td colspan="5" class="text-center py-6 text-slate-400">Cargando datos...</td></tr>';
    
    try {
        const res = await fetch('/api/proveedores/' + rif + '/perfil');
        const data = await res.json();
        if(data.success) {
            const p = data.proveedor;
            document.getElementById('perfil_prov_nombre').innerText = p.razon_social;
            document.getElementById('perfil_prov_banco').innerText = p.banco_nombre || 'N/A';
            
            const ordenes = data.ordenes || [];
            document.getElementById('perfil_total_ordenes').innerText = ordenes.length;
            
            let totalUsd = 0;
            let html = '';
            if(ordenes.length === 0) {
                html = '<tr><td colspan="5" class="text-center py-6 text-slate-400">No hay órdenes para este proveedor</td></tr>';
            } else {
                ordenes.forEach(o => {
                    totalUsd += parseFloat(o.total_usd || 0);
                    html += `<tr>
                        <td class="px-4 py-3 font-bold text-slate-700">${o.id}</td>
                        <td class="px-4 py-3 text-slate-500">${o.fecha}</td>
                        <td class="px-4 py-3 font-medium text-slate-600">${o.proyecto}</td>
                        <td class="px-4 py-3 text-right font-black text-emerald-700">$${parseFloat(o.total_usd||0).toLocaleString('es-VE',{minimumFractionDigits:2})}</td>
                        <td class="px-4 py-3 text-center"><a href="/api/pdf/${o.id}" target="_blank" class="text-brand-600 hover:text-brand-800 font-bold">PDF</a></td>
                    </tr>`;
                });
                document.getElementById('perfil_ultima_fecha').innerText = ordenes[0].fecha;
            }
            document.getElementById('perfil_total_usd').innerText = '$' + totalUsd.toLocaleString('es-VE',{minimumFractionDigits:2});
            document.getElementById('bodyPerfilOrdenes').innerHTML = html;
            
            document.getElementById('btn-editar-perfil-prov').onclick = () => {
                editarProveedor(p.id, p.razon_social, p.rif, p.direccion, p.telefono, p.banco_nombre, p.cuenta_bancaria, p.tipo_cuenta);
            };
        } else {
            Swal.fire('Error', 'Proveedor no encontrado', 'error');
            switchTab('proveedores');
        }
    } catch(e) {
        Swal.fire('Error', 'Error de conexión', 'error');
        switchTab('proveedores');
    }
}
</script>
