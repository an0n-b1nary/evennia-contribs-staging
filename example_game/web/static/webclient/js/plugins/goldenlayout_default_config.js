/*
 * Game default layout. Local storage can preserve an earlier layout for each
 * browser, so this default applies to new client layouts only.
 */
var goldenlayout_config = {
    content: [{
        type: "column",
        content: [{
            type: "row",
            content: [{
                type: "column",
                content: [{
                    type: "component",
                    componentName: "Main",
                    isClosable: false,
                    tooltip: "Main - drag to desired position.",
                    componentState: {
                        types: "untagged",
                        updateMethod: "newlines",
                    },
                }]
            }],
        }, {
            type: "component",
            componentName: "input",
            id: "inputComponent",
            height: 12,
            isClosable: false,
            tooltip: "Input - The last input in the layout is always the default.",
        }]
    }]
};
