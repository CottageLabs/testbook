let testbook = {};

testbook.state = {
    currentTestSet: false,
    selected: []
}

testbook.init = function() {
    $(".navlink").on("click", testbook.navClick);
    $(".add-remove").on("click.AddRemove", testbook.toggleAddRemove);
    $(".clear-selected").on("click.ClearSelected", testbook.clearSelected);
    $(".download-selection").on("click.DownloadSelection", testbook.downloadSelection);

    let selected = window.localStorage.getItem("selected")
    if (!selected) {
        window.localStorage.setItem("selected", JSON.stringify([]));
    }

    testbook.updateSelectedCount();
    testbook.updateSelectedHighlights();

    let hash = window.location.hash
    if (hash) {
        hash = hash.substring(1);
        testbook.loadTarget(hash);
    }
}

testbook.navClick = function(event) {
    event.preventDefault();

    let el = $(event.target);
    let target = el.attr("data-target");
    testbook.loadTarget(target);
}

testbook._testSetId = function(suite, set) {
    return suite + "__" + set
}

testbook.loadTarget = function(target) {
    let bits = target.split("/");

    let suite = false;
    let set = false;
    let test = false;

    if (bits.length === 2) {
        suite = bits[0]
        set = bits[1]
    } else if (bits.length === 3) {
        suite = bits[0]
        set = bits[1]
        test = bits[2]
    } else {
        alert("unable to identify testset to load")
    }

    let targetId = testbook._testSetId(suite, set);
    if (targetId === testbook.state.currentTestSet) {
        let top = document.getElementById(test).offsetTop;
        window.scrollTo(0, top);
        history.pushState(null, null, "#" + target);
        return;
    }

    testbook.loadTestSet({
        target: target,
        suite: suite,
        set: set,
        test: test
    })
}

testbook.loadTestSet = function(params) {
    let id = testbook._testSetId(params.suite, params.set);
    $.get({
        url: id + ".html",
        success: testbook.receivedTestSetHTML(id, params),
        error: testbook.errorTestSetHTML
    })
}

testbook.receivedTestSetHTML = function(id, params) {
    return function(data) {
        $("#tests").html(data)
        testbook.state.currentTestSet = id;
        let top = document.getElementById(params.test).offsetTop;
        window.scrollTo(0, top);

        history.pushState(null, null, "#" + params.target);

        $(".add-remove").off("click.AddRemove").on("click.AddRemove", testbook.toggleAddRemove);
        $(".naventry").removeClass("navselected");
        $("#nav_" + params.suite).addClass("navselected");
        $("#nav_" + id).addClass("navselected");
    }
}

testbook.errorTestSetHTML = function(data) {
    alert("error retrieving test set")
}

testbook.toggleAddRemove = function(event) {
    let el = $(event.target);
    let target = el.attr("data-target");
    let action = el.attr("data-action");

    if (action === "add") {
        testbook.addSelection(target);
        el.attr("data-action", "remove");
        let removeText = el.attr("data-remove")
        el.html(removeText);
    } else if (action === "remove") {
        testbook.removeSelection(target);
        el.attr("data-action", "add");
        let addText = el.attr("data-add")
        el.html(addText);
    }

    testbook.updateSelectedCount();
    testbook.updateSelectedHighlights();
}

testbook.updateSelectedCount = function() {
    let current = window.localStorage.getItem("selected");
    let data = JSON.parse(current);
    $(".selected-count").html(data.length);
}

testbook.updateSelectedHighlights = function() {
    let current = window.localStorage.getItem("selected");
    let data = JSON.parse(current);
    $(".naventry").removeClass("testselected");
    for (let i = 0; i < data.length; i++) {
        let entry = data[i];
        let id = entry.replaceAll("/", "__")
        $("#nav_" + id).addClass("testselected");
    }
}

testbook.addSelection = function(target) {
    let current = window.localStorage.getItem("selected")
    let data = JSON.parse(current)
    if (!(target in data)) {
        data.push(target);
    }
    window.localStorage.setItem("selected", JSON.stringify(data))
}

testbook.removeSelection = function(target) {
    let current = window.localStorage.getItem("selected")
    let data = JSON.parse(current)
    let idx = data.indexOf(target);
    if (idx > -1) {
        data.splice(idx, 1);
    }
    window.localStorage.setItem("selected", JSON.stringify(data))
}

testbook.clearSelected = function(event) {
    event.preventDefault();

    let sure = confirm("Are you sure you want to clear your selection?");
    if (!sure) {
        return;
    }
    
    window.localStorage.setItem("selected", JSON.stringify([]));
    testbook.updateSelectedCount();
    testbook.updateSelectedHighlights();
}

testbook.downloadSelection = function(event) {
    event.preventDefault();

    let current = window.localStorage.getItem("selected")
    let data = JSON.parse(current)

    let promises = [];
    for (let i = 0; i < data.length; i++) {
        let entry = data[i];
        let id = entry.replaceAll("/", "__")
        promises.push(new Promise((resolve, reject) => {
            $.get({
                url: "test_csvs/" + id + ".csv",
                success: resolve,
                error: reject
            })
        }))
    }

    Promise.all(promises).then((values) => {
        let content = "data:text/csv;charset=utf-8,"
        content += values.join("\n");
        let encodedUri = encodeURI(content);
        let link = document.createElement("a");
        link.setAttribute("href", encodedUri);
        link.setAttribute("download", "testbook.csv");
        document.body.appendChild(link); // Required for FF
        link.click(); // This will download the data file named "my_data.csv".
    })
}