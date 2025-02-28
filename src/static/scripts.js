function toggleCheckboxes(source) {
    checkboxes = document.getElementsByName('agent');
    for(let i=0, n=checkboxes.length;i<n;i++) {
        checkboxes[i].checked = source.checked;
    }
}

function toggleTeamCheckboxes(manager) {
    checkboxes = document.getElementsByClassName(manager);
    for(let i=0, n=checkboxes.length;i<n;i++) {
        checkboxes[i].checked = document.getElementById(manager.replace(" ","") + 'CheckAll').checked;
    }
}

function showEmailOptions(validDomains) {
    var optIn = document.getElementById("email-opt-in").checked;
    var emailCol = document.getElementById("email-col");
    var emailAddr = document.getElementById("email-address");
    var recurrence = document.getElementsByName("recurrence");
    var form = document.getElementById("combinedForm");

    if (optIn){
        emailCol.style.display = "block";
        emailAddr.setAttribute("required", "true");

        form.onsubmit = function() {
            return emailVerification(validDomains) && checkAgentsSelected();
        };

        // Ensure at least one radio button is required
        recurrence[0].setAttribute("required", "true");
    } else {
        emailCol.style.display = "none";
        emailAddr.removeAttribute("required");
        recurrence[0].removeAttribute("required");
        form.onsubmit = function() {
            return checkAgentsSelected();
        };
    }
}

function checkAgentsSelected() {
    var agents = document.getElementsByName("agent");
    for (var i = 0; i < agents.length; i++) {
        if (agents[i].checked) {
            return true; // At least one agent is selected
        }
    }
    alert("Please select at least one agent!");
    return false; // No agents selected
}

function emailVerification(validDomains) {
    let email = document.getElementById("email-address").value;
    let domain = email.split('@')[1];
    if (validDomains.includes(domain)) {
        console.log("Valid email address: " + email);
        return true; // Allow form submission
    } else {
        console.log("Invalid email address: " + email);
        alert("Please enter a valid email address! (e.g. " + validDomains.join(', ') + ")");
        return false; // Prevent form submission
    }
}

async function downloadCSV() {
    window.location.href = '/download_csv';
    alert("CSV download started - please check your downloads folder!");
}

function setDateRange(startDate, endDate) {
    const startTime = '03:00';  // UTC start time
    const endTime = '02:30';    // UTC end time
    
    
    document.getElementById('startdatelabel').value = startDate;
    document.getElementById('enddatelabel').value = endDate;
    document.getElementById('starttimelabel').value = startTime;
    document.getElementById('endtimelabel').value = endTime;
}

function setToday() {
    const today = new Date();
    const tomorrow = new Date(today);
    tomorrow.setDate(today.getDate() + 1);

    const todayFormatted = today.toISOString().split('T')[0];
    const tomorrowFormatted = tomorrow.toISOString().split('T')[0];

    setDateRange(todayFormatted, tomorrowFormatted);
}

function setYesterday(){
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);

    const yesterdayFormatted = yesterday.toISOString().split('T')[0];
    const todayFormatted = today.toISOString().split('T')[0];

    setDateRange(yesterdayFormatted, todayFormatted);
}

function setThisWeek() {
    const today = new Date();
    const dayOfWeek = today.getDay(); // 0 (Sunday) to 6 (Saturday)
    const firstDayOfWeek = new Date(today.setDate(today.getDate() - dayOfWeek + (dayOfWeek === 0 ? -6 : 1))).toISOString().split('T')[0];
    const lastDayOfWeek = new Date(today.setDate(today.getDate() - today.getDay() + 6)).toISOString().split('T')[0];

    setDateRange(firstDayOfWeek, lastDayOfWeek);
}

function setLastWeek() {
    const today = new Date();
    const dayOfWeek = today.getDay(); // 0 (Sunday) to 6 (Saturday)
    const firstDayOfLastWeek = new Date(today.setDate(today.getDate() - dayOfWeek - 7 + (dayOfWeek === 0 ? -6 : 1))).toISOString().split('T')[0];
    const lastDayOfLastWeek = new Date(today.setDate(today.getDate() - today.getDay() + 6)).toISOString().split('T')[0];

    setDateRange(firstDayOfLastWeek, lastDayOfLastWeek);
}

function setLastMonth() {
    const today = new Date();
    const firstDayOfLastMonth = new Date(today.getFullYear(), today.getMonth() - 1, 1).toISOString().split('T')[0];
    const lastDayOfLastMonth = new Date(today.getFullYear(), today.getMonth(), 0).toISOString().split('T')[0];

    setDateRange(firstDayOfLastMonth, lastDayOfLastMonth);
}

function setLastThreeMonths() {
    const today = new Date();
    const firstDayOfLastThreeMonths = new Date(today.getFullYear(), today.getMonth() - 3, 1).toISOString().split('T')[0];
    const lastDayOfLastThreeMonths = new Date(today.getFullYear(), today.getMonth(), 0).toISOString().split('T')[0];

    setDateRange(firstDayOfLastThreeMonths, lastDayOfLastThreeMonths);
}
