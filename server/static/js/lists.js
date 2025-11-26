
/*
 
 */
class List {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.container.classList.add('list-container');
        this.elements = [];
    }

    add(element) {
        this.elements.push(element);
        this.render();
    }

    render() {
        this.container.innerHTML = '';
        

        this.elements.forEach(element => {
            const inner = document.createElement('div');
            inner.className = 'list-element-inner';
        
            if (element.createdAt) {
                var date = new Date(element.createdAt);
                var dateString = date.toLocaleDateString();
            } else {
                var dateString = '';
            }

            inner.innerHTML = `
                <i class="ph ${element.icon} list-element-icon"></i>
                <span class="list-element-id">${element.id}</span>
                <span class="list-element-text">
                    <h3>${element.title}</h3>
                    <p style="position:absolute;top:2rem;">${element.description}</p>
                </span>
                <span class="list-labels">
                    ${element.labels.map(label => `<span class="list-label"> <span class="list-label-circle" style="background-color: ${label.color}"></span> ${label.text}  </span>`).join('')}
                </span>
                <span class="list-assignees">
                    ${element.assignees.map(assignee => `<span class="list-assignee"> <i class="ph ph-user"></i>  ${assignee}</span>`).join('')}
                </span>
                <span class="list-date">
                    ${dateString}
                </span>
            `;
            
            const elDiv = document.createElement('div');
            elDiv.className = 'list-element';
            elDiv.appendChild(inner);

            this.container.appendChild(elDiv);
        });
    }
}

