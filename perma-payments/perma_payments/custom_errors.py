from django.shortcuts import render

def bad_request(request):
    context = {
        'heading': "400 Bad Request",
        'message': "The browser (or proxy) sent a request that this server could not understand."
    }
    return render(request, 'generic.html', context, status=400)
