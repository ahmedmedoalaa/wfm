document.getElementById('uploadForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fileInput = document.getElementById('excelFile');
    const force = document.getElementById('forceOverwrite').checked;
    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    try {
        const res = await fetch(`/upload${force ? '?force=true' : ''}`, {
            method: 'POST',
            body: formData,
        });

        const data = await res.json();
        document.getElementById('uploadMessage').textContent = data.message || data.error;
    } catch (err) {
        document.getElementById('uploadMessage').textContent = 'Upload failed.';
    }
});

async function loadDropdowns() {
    const res = await fetch('/search');
    const html = await res.text();
    const agents = [...html.matchAll(/value="(.*?)"/g)].map(x => x[1]).filter(v => v !== "");

    const agentDropdown = document.getElementById('agentDropdown');
    agents.forEach(agent => {
        const opt = document.createElement('option');
        opt.value = agent;
        opt.textContent = agent;
        agentDropdown.appendChild(opt);
    });

    const dates = [...html.matchAll(/option value="(\d{4}-\d{2}-\d{2})"/g)].map(x => x[1]);
    const dateDropdown = document.getElementById('dateDropdown');
    dates.forEach(date => {
        const opt = document.createElement('option');
        opt.value = date;
        opt.textContent = date;
        dateDropdown.appendChild(opt);
    });
}

async function searchSchedules() {
    const agent = document.getElementById('agentDropdown').value;
    const date = document.getElementById('dateDropdown').value;

    const query = new URLSearchParams();
    if (agent) query.append('agent', agent);
    if (date) query.append('date', date);

    const res = await fetch(`/search?${query.toString()}`);
    const html = await res.text();
    const results = html.match(/<table.*<\/table>/s);
    document.getElementById('searchResults').innerHTML = results ? results[0] : 'No results';
}

async function loadAllSchedules() {
    const res = await fetch('/view-db');
    const html = await res.text();
    const table = html.match(/<table.*<\/table>/s);
    document.getElementById('allSchedules').innerHTML = table ? table[0] : 'No schedules';
}

// On page load
loadDropdowns();
loadAllSchedules();
